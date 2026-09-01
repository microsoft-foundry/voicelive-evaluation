"""Tests for simulated-user processing in the container app."""

import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import processor
from app.config import SessionConfig
from app import jobs
from app.jobs import JobProgress, JobStatus
from app.main import RunAudioTestsRequest
from app.persona_simulation import SimulationAssets, SimulationIncompleteError
from app.storage import DatasetEntry
from app.voicelive_client import ConversationTurn


class FakeVoiceLiveClient:
    def __init__(self, turns):
        self.turns = list(turns)
        self.audio_inputs = []
        self.configured_with = None

    async def configure_session(self, config):
        self.configured_with = config

    async def process_audio(self, audio_data, **_kwargs):
        self.audio_inputs.append(audio_data)
        result = self.turns.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class FakeStorage:
    def download_audio_file(self, _path, _temp_dir):
        return "seed.wav"


class FakeClientContext:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, *_args):
        return False


class FakeVoiceLiveClientFactory:
    @classmethod
    def from_session_config(cls, **_kwargs):
        return FakeClientContext(FakeVoiceLiveClient([]))

    def __new__(cls, *_args, **_kwargs):
        return FakeClientContext(FakeVoiceLiveClient([]))


class PersonaSimulationProcessorTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_rejects_excessive_turns_and_empty_model(self):
        base_request = {
            "dataset_path": "datasets/seed.jsonl",
            "simulation_config": {
                "persona": {},
                "scenario": {},
                "data": {},
            },
        }

        with self.assertRaisesRegex(ValueError, "less than or equal to 100"):
            RunAudioTestsRequest.model_validate(
                {
                    **base_request,
                    "simulation_config": {
                        **base_request["simulation_config"],
                        "max_turns": 101,
                    },
                }
            )
        with self.assertRaisesRegex(ValueError, "at least 1 character"):
            RunAudioTestsRequest.model_validate(
                {
                    **base_request,
                    "simulation_config": {
                        **base_request["simulation_config"],
                        "model": "",
                    },
                }
            )
        for invalid_turns in (True, "4"):
            with self.assertRaisesRegex(ValueError, "valid integer"):
                RunAudioTestsRequest.model_validate(
                    {
                        **base_request,
                        "simulation_config": {
                            **base_request["simulation_config"],
                            "max_turns": invalid_turns,
                        },
                    }
                )
        with self.assertRaisesRegex(ValueError, "non-empty string"):
            RunAudioTestsRequest.model_validate(
                {
                    **base_request,
                    "simulation_config": {
                        **base_request["simulation_config"],
                        "model": "   ",
                    },
                }
            )

    async def test_terminal_progress_accounts_for_failed_turns(self):
        progress = JobProgress(total_files=4, files_processed=1, files_failed=3)

        self.assertEqual(progress.to_dict()["percent_complete"], 100.0)

    async def test_persisted_progress_accounts_for_failed_turns(self):
        table_client = unittest.mock.Mock()
        table_client.get_entity.return_value = {
            "RowKey": "job-1",
            "files_processed": 1,
            "files_failed": 3,
            "total_files": 4,
        }

        with patch.object(jobs, "_get_table_client", return_value=table_client):
            result = jobs.load_job_from_table("job-1")

        self.assertEqual(result["progress"]["percent_complete"], 100.0)

    async def test_alternates_audio_and_completes_progress(self):
        tested_client = FakeVoiceLiveClient(
            [
                ConversationTurn(
                    user_transcription="I replaced the relay.",
                    assistant_response="Which unit was repaired?",
                    response_audio_chunks=[b"assistant-one"],
                ),
                ConversationTurn(
                    user_transcription="Unit U-42.",
                    assistant_response="The report is complete.",
                    response_audio_chunks=[b"assistant-two"],
                ),
            ]
        )
        simulator_client = FakeVoiceLiveClient(
            [
                ConversationTurn(
                    assistant_response="Understood. Let's hear it.",
                ),
                ConversationTurn(
                    assistant_response="Unit U-42.",
                    response_audio_chunks=[b"persona-two"],
                )
            ]
        )
        on_file_complete = AsyncMock()
        config = SessionConfig()
        assets = SimulationAssets(persona={}, scenario={}, data={}, max_turns=2)
        seed = DatasetEntry(
            wav_path="seed.wav",
            question="I replaced the relay.",
            conversation_id="repair-1",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(processor, "load_audio_file", return_value=b"seed-audio"),
                patch.object(processor.asyncio, "sleep", new=AsyncMock()),
                patch.object(
                    processor.job_manager,
                    "update_job_progress",
                    new=AsyncMock(),
                ),
            ):
                results = await processor.process_conversation(
                    entries=[seed],
                    client=tested_client,
                    config=config,
                    storage=FakeStorage(),
                    temp_dir=temp_dir,
                    job_id="job-1",
                    conversation_id="repair-1",
                    on_file_complete=on_file_complete,
                    simulation_assets=assets,
                    simulator_client=simulator_client,
                    simulator_config=config,
                )

        self.assertEqual(tested_client.audio_inputs, [b"seed-audio", b"persona-two"])
        self.assertEqual(
            simulator_client.audio_inputs,
            [b"assistant-one", b"assistant-one"],
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[1]["source_file"], "(simulated)")
        self.assertEqual(results[1]["query"][-1]["content"][0]["text"], "Unit U-42.")
        self.assertEqual(on_file_complete.await_count, 2)

    async def test_stops_after_recording_turn_when_assistant_audio_is_missing(self):
        tested_client = FakeVoiceLiveClient(
            [
                ConversationTurn(
                    user_transcription="I replaced the relay.",
                    assistant_response="I need the unit identifier.",
                )
            ]
        )
        simulator_client = FakeVoiceLiveClient([])
        on_file_complete = AsyncMock()
        config = SessionConfig()
        assets = SimulationAssets(persona={}, scenario={}, data={}, max_turns=4)

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(processor, "load_audio_file", return_value=b"seed-audio"),
                patch.object(
                    processor.job_manager,
                    "update_job_progress",
                    new=AsyncMock(),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "Simulation incomplete"):
                    await processor.process_conversation(
                        entries=[DatasetEntry(wav_path="seed.wav")],
                        client=tested_client,
                        config=config,
                        storage=FakeStorage(),
                        temp_dir=temp_dir,
                        job_id="job-1",
                        conversation_id="repair-1",
                        on_file_complete=on_file_complete,
                        simulation_assets=assets,
                        simulator_client=simulator_client,
                        simulator_config=config,
                    )

        self.assertEqual(on_file_complete.await_count, 1)
        self.assertEqual(simulator_client.audio_inputs, [])

    async def test_wraps_simulator_exception_with_partial_results(self):
        tested_client = FakeVoiceLiveClient(
            [
                ConversationTurn(
                    user_transcription="Good morning.",
                    assistant_response="How can I help?",
                    response_audio_chunks=[b"assistant-audio"],
                )
            ]
        )
        simulator_client = FakeVoiceLiveClient(
            [ValueError("simulator transport failed")]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(processor, "load_audio_file", return_value=b"seed-audio"),
                patch.object(
                    processor.job_manager,
                    "update_job_progress",
                    new=AsyncMock(),
                ),
            ):
                with self.assertRaises(SimulationIncompleteError) as raised:
                    await processor.process_conversation(
                        entries=[DatasetEntry(wav_path="seed.wav")],
                        client=tested_client,
                        config=SessionConfig(),
                        storage=FakeStorage(),
                        temp_dir=temp_dir,
                        job_id="job-1",
                        conversation_id="repair-1",
                        simulation_assets=SimulationAssets(
                            persona={}, scenario={}, data={}, max_turns=2
                        ),
                        simulator_client=simulator_client,
                        simulator_config=SessionConfig(),
                    )

        self.assertIn("simulator transport failed", str(raised.exception))
        self.assertEqual(len(raised.exception.partial_results), 1)

    async def test_dataset_job_fails_and_uploads_partial_simulation_results(self):
        seed = DatasetEntry(wav_path="seed.wav", conversation_id="repair-1")
        partial_result = {
            "conversation_id": "repair-1",
            "source_file": "seed.wav",
            "turn_number": 1,
        }
        storage = FakeStorage()
        storage.download_dataset = lambda _path: ("seed.jsonl", [seed], "seed.jsonl")
        storage.upload_results = unittest.mock.Mock(return_value="results/job-1.jsonl")
        update_status = AsyncMock()
        update_progress = AsyncMock()
        observed_simulator_config = None

        async def fail_after_first_turn(**kwargs):
            nonlocal observed_simulator_config
            observed_simulator_config = kwargs["simulator_config"]
            await kwargs["on_file_complete"](success=True)
            raise SimulationIncompleteError(
                "Simulation incomplete after turn 1",
                [partial_result],
            )

        with (
            patch.dict(os.environ, {"AZURE_VOICELIVE_ENDPOINT": "https://example"}),
            patch.object(processor, "BlobStorageClient", return_value=storage),
            patch.object(processor, "VoiceLiveClient", new=FakeVoiceLiveClientFactory),
            patch.object(processor, "DefaultAzureCredential", return_value=object()),
            patch.object(processor, "process_conversation", side_effect=fail_after_first_turn),
            patch.object(processor.job_manager, "update_job_status", new=update_status),
            patch.object(processor.job_manager, "update_job_progress", new=update_progress),
        ):
            await processor.process_dataset(
                job_id="job-1",
                dataset_path="datasets/seed.jsonl",
                session_config={
                    "push_to_talk": True,
                    "transcription_model": "gpt-4o-mini-transcribe",
                },
                simulation_config={
                    "persona": {},
                    "scenario": {},
                    "data": {},
                    "max_turns": 4,
                },
            )

        upload_metadata = storage.upload_results.call_args.kwargs["metadata"]
        self.assertEqual(upload_metadata["files_processed"], 1)
        self.assertEqual(upload_metadata["files_failed"], 3)
        self.assertEqual(storage.upload_results.call_args.kwargs["results"], [partial_result])
        final_status = update_status.await_args_list[-1]
        self.assertEqual(final_status.args[1], JobStatus.FAILED)
        self.assertEqual(final_status.kwargs["output_path"], "results/job-1.jsonl")
        self.assertEqual(final_status.kwargs["results_count"], 1)
        self.assertEqual(
            observed_simulator_config.audio,
            processor.DEFAULT_SESSION_CONFIG.audio,
        )
        self.assertFalse(observed_simulator_config.turn_detection.enable_barge_in)
        self.assertTrue(observed_simulator_config.push_to_talk)
        self.assertEqual(
            observed_simulator_config.transcription_model,
            "gpt-4o-mini-transcribe",
        )
        self.assertIsNone(observed_simulator_config.agent)

    async def test_legacy_dataset_error_retains_completed_job_status(self):
        seed = DatasetEntry(wav_path="seed.wav", conversation_id="repair-1")
        storage = FakeStorage()
        storage.download_dataset = lambda _path: ("seed.jsonl", [seed], "seed.jsonl")
        storage.upload_results = unittest.mock.Mock(return_value="results/job-1.jsonl")
        update_status = AsyncMock()

        with (
            patch.dict(os.environ, {"AZURE_VOICELIVE_ENDPOINT": "https://example"}),
            patch.object(processor, "BlobStorageClient", return_value=storage),
            patch.object(processor, "VoiceLiveClient", new=FakeVoiceLiveClientFactory),
            patch.object(processor, "DefaultAzureCredential", return_value=object()),
            patch.object(
                processor,
                "process_conversation",
                new=AsyncMock(side_effect=ValueError("legacy turn failed")),
            ),
            patch.object(processor.job_manager, "update_job_status", new=update_status),
            patch.object(
                processor.job_manager,
                "update_job_progress",
                new=AsyncMock(),
            ),
        ):
            await processor.process_dataset(
                job_id="job-1",
                dataset_path="datasets/seed.jsonl",
            )

        self.assertEqual(update_status.await_args_list[-1].args[1], JobStatus.COMPLETED)


if __name__ == "__main__":
    unittest.main()