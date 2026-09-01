"""Tests for structured simulated-user assets."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import voice_agent_audio_input_evaluation as harness
from persona_simulation import (
    SimulationAssets,
    SimulationIncompleteError,
    build_simulator_instructions,
    load_simulation_assets,
    simulation_assets_from_dict,
)


class PersonaSimulationTests(unittest.TestCase):
    def test_loads_relative_assets_and_builds_stable_instructions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "persona.json").write_text(
                json.dumps({"name": "Alex", "communication_style": "concise"}),
                encoding="utf-8",
            )
            (root / "scenario.json").write_text(
                json.dumps({"id": "repair-flow", "goal": "report a repaired relay"}),
                encoding="utf-8",
            )
            (root / "data.json").write_text(
                json.dumps({"unit": {"unit_id": "U-42"}}), encoding="utf-8"
            )
            config_path = root / "simulation.json"
            config_path.write_text(
                json.dumps(
                    {
                        "persona_path": "persona.json",
                        "scenario_path": "scenario.json",
                        "data_path": "data.json",
                        "max_turns": 4,
                    }
                ),
                encoding="utf-8",
            )

            assets = load_simulation_assets(str(config_path))
            instructions = build_simulator_instructions(assets)

            self.assertEqual(assets.max_turns, 4)
            self.assertEqual(assets.data, {"unit": {"unit_id": "U-42"}})
            self.assertIn('"name":"Alex"', instructions)
            self.assertIn('"id":"repair-flow"', instructions)
            self.assertIn('"unit_id":"U-42"', instructions)

    def test_default_credential_flag_overrides_configured_key_and_token(self):
        args = SimpleNamespace(use_default_credential=True, api_key="cli-key")

        with (
            patch.dict(
                os.environ,
                {
                    "AZURE_VOICELIVE_API_KEY": "environment-key",
                    "AZURE_VOICELIVE_BEARER_TOKEN": "environment-token",
                },
            ),
            patch.object(harness, "DefaultAzureCredential") as default_credential,
            patch.object(harness, "AzureKeyCredential") as key_credential,
        ):
            credential = harness.create_voicelive_credential(args)

        self.assertIs(credential, default_credential.return_value)
        default_credential.assert_called_once_with()
        key_credential.assert_not_called()

    def test_rejects_missing_asset_reference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "simulation.json"
            config_path.write_text(
                json.dumps(
                    {
                        "persona_path": "persona.json",
                        "scenario_path": "scenario.json",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "data_path"):
                load_simulation_assets(str(config_path))

    def test_rejects_non_positive_max_turns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in ("persona.json", "scenario.json", "data.json"):
                (root / name).write_text("{}", encoding="utf-8")
            config_path = root / "simulation.json"
            config_path.write_text(
                json.dumps(
                    {
                        "persona_path": "persona.json",
                        "scenario_path": "scenario.json",
                        "data_path": "data.json",
                        "max_turns": 0,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "max_turns"):
                load_simulation_assets(str(config_path))

    def test_rejects_excessive_max_turns_and_empty_model(self):
        with self.assertRaisesRegex(ValueError, "max_turns"):
            simulation_assets_from_dict(
                {"persona": {}, "scenario": {}, "data": {}, "max_turns": 101}
            )
        with self.assertRaisesRegex(ValueError, "model"):
            simulation_assets_from_dict(
                {"persona": {}, "scenario": {}, "data": {}, "model": ""}
            )

    def test_validates_inline_cloud_assets(self):
        assets = simulation_assets_from_dict(
            {
                "persona": {"name": "Alex"},
                "scenario": {"id": "repair-flow"},
                "data": {"unit_id": "U-42"},
            }
        )

        self.assertEqual(assets.max_turns, 8)
        with self.assertRaisesRegex(ValueError, "scenario"):
            simulation_assets_from_dict(
                {"persona": {}, "scenario": "repair-flow", "data": {}}
            )


class SimulatedConversationTests(unittest.IsolatedAsyncioTestCase):
    async def test_alternates_assistant_and_persona_audio(self):
        tested_connection = object()
        simulator_connection = object()
        tested_inputs = []
        simulator_inputs = []
        tested_turns = [
            harness.ConversationTurn(
                user_transcription="I replaced the relay.",
                assistant_response="Which unit was repaired?",
                response_audio_chunks=[b"assistant-one"],
            ),
            harness.ConversationTurn(
                user_transcription="Unit U-42.",
                assistant_response="The report is complete.",
                response_audio_chunks=[b"assistant-two"],
            ),
        ]
        simulated_turns = [
            harness.ConversationTurn(
                assistant_response="Understood. Let's hear it.",
            ),
            harness.ConversationTurn(
                assistant_response="Unit U-42.",
                response_audio_chunks=[b"persona-two"],
            )
        ]

        async def fake_process_audio(connection, audio_data, *_args, **_kwargs):
            if connection is tested_connection:
                tested_inputs.append(audio_data)
                return tested_turns.pop(0)
            simulator_inputs.append(audio_data)
            return simulated_turns.pop(0)

        assets = SimulationAssets(persona={}, scenario={}, data={}, max_turns=2)
        config = harness.SessionConfig()
        seed = harness.DatasetEntry(
            audio_path="seed.wav",
            question="I replaced the relay.",
            conversation_id="repair-1",
        )

        with tempfile.TemporaryDirectory() as output_dir:
            with (
                patch.object(
                    harness,
                    "configure_session",
                    new=AsyncMock(),
                ),
                patch.object(harness, "load_audio_file", return_value=b"seed-audio"),
                patch.object(harness, "process_audio", side_effect=fake_process_audio),
                patch.object(harness, "save_response_audio"),
                patch.object(harness.asyncio, "sleep", new=AsyncMock()),
            ):
                results = await harness.process_conversation(
                    [seed],
                    tested_connection,
                    config,
                    output_dir,
                    simulation_assets=assets,
                    simulator_connection=simulator_connection,
                    simulator_config=config,
                )

        self.assertEqual(tested_inputs, [b"seed-audio", b"persona-two"])
        self.assertEqual(simulator_inputs, [b"assistant-one", b"assistant-one"])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[1]["source_file"], "(simulated)")
        self.assertEqual(results[1]["query"][-1]["content"][0]["text"], "Unit U-42.")

    async def test_stops_after_recording_turn_when_assistant_audio_is_missing(self):
        tested_connection = object()
        simulator_connection = object()
        process_audio = AsyncMock(
            return_value=harness.ConversationTurn(
                user_transcription="I replaced the relay.",
                assistant_response="I need the unit identifier.",
            )
        )
        config = harness.SessionConfig()
        assets = SimulationAssets(persona={}, scenario={}, data={}, max_turns=4)

        with tempfile.TemporaryDirectory() as output_dir:
            with (
                patch.object(
                    harness,
                    "configure_session",
                    new=AsyncMock(),
                ),
                patch.object(harness, "load_audio_file", return_value=b"seed-audio"),
                patch.object(harness, "process_audio", new=process_audio),
            ):
                with self.assertRaisesRegex(RuntimeError, "Simulation incomplete"):
                    await harness.process_conversation(
                        [harness.DatasetEntry(audio_path="seed.wav")],
                        tested_connection,
                        config,
                        output_dir,
                        simulation_assets=assets,
                        simulator_connection=simulator_connection,
                        simulator_config=config,
                    )

        self.assertEqual(process_audio.await_count, 1)

    async def test_wraps_simulator_exception_with_partial_results(self):
        tested_connection = object()
        simulator_connection = object()

        async def process_audio(connection, *_args, **_kwargs):
            if connection is tested_connection:
                return harness.ConversationTurn(
                    user_transcription="Good morning.",
                    assistant_response="How can I help?",
                    response_audio_chunks=[b"assistant-audio"],
                )
            raise ValueError("simulator transport failed")

        with tempfile.TemporaryDirectory() as output_dir:
            with (
                patch.object(harness, "configure_session", new=AsyncMock()),
                patch.object(harness, "load_audio_file", return_value=b"seed-audio"),
                patch.object(harness, "process_audio", side_effect=process_audio),
                patch.object(harness, "save_response_audio"),
            ):
                with self.assertRaises(SimulationIncompleteError) as raised:
                    await harness.process_conversation(
                        [harness.DatasetEntry(audio_path="seed.wav")],
                        tested_connection,
                        harness.SessionConfig(),
                        output_dir,
                        simulation_assets=SimulationAssets(
                            persona={}, scenario={}, data={}, max_turns=2
                        ),
                        simulator_connection=simulator_connection,
                        simulator_config=harness.SessionConfig(),
                    )

        self.assertIn("simulator transport failed", str(raised.exception))
        self.assertEqual(len(raised.exception.partial_results), 1)

    async def test_main_preserves_partial_results_and_fails_incomplete_run(self):
        partial_result = {
            "conversation_id": "repair-1",
            "source_file": "seed.wav",
            "turn_number": 1,
        }
        args = SimpleNamespace(
            test_files_path="seed.jsonl",
            model="gpt-realtime",
            voice="en-US-Ava:DragonHDLatestNeural",
            voice_type="azure-standard",
            sample_rate=24000,
            push_to_talk=False,
            enable_barge_in=True,
            noise_reduction="azure_deep_noise_suppression",
            echo_cancellation="server_echo_cancellation",
            transcription_model=None,
            vad_type="azure_semantic_vad_multilingual",
            vad_threshold=None,
            silence_duration_ms=None,
            use_eou_detection=True,
            eou_model="semantic_detection_v1_multilingual",
            agent_name=None,
            project_name=None,
            agent_version=None,
            foundry_resource_override=None,
            authentication_identity_client_id=None,
            output_dir="output",
            evaluation_dir=None,
            aggregate_eval_file=None,
            session_mode="per-conversation",
            simulation_config="simulation.json",
            session_suffix=None,
            skip_evaluation=False,
            evaluators="default",
            eval_group_by="dataset",
            eval_object_id=None,
            upload_dataset=False,
        )

        class ConnectionContext:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *_args):
                return False

        with tempfile.TemporaryDirectory() as output_dir:
            args.output_dir = output_dir
            with (
                patch.dict(os.environ, {"AZURE_VOICELIVE_ENDPOINT": "https://example"}),
                patch.object(
                    harness,
                    "read_dataset",
                    return_value=[
                        harness.DatasetEntry(
                            audio_path="seed.wav",
                            conversation_id="repair-1",
                        )
                    ],
                ),
                patch.object(
                    harness,
                    "load_simulation_assets",
                    return_value=SimulationAssets(
                        persona={}, scenario={}, data={}, max_turns=4
                    ),
                ),
                patch.object(harness, "create_voicelive_credential", return_value=object()),
                patch.object(harness, "voicelive_connect", return_value=ConnectionContext()),
                patch.object(
                    harness,
                    "configure_session",
                    new=AsyncMock(),
                ) as configure_session,
                patch.object(
                    harness,
                    "process_conversation",
                    new=AsyncMock(
                        side_effect=SimulationIncompleteError(
                            "Simulation incomplete after turn 1",
                            [partial_result],
                        )
                    ),
                ),
                patch.object(harness, "write_results", return_value="results.jsonl") as write_results,
                patch.object(harness, "write_operational_summary"),
                patch.object(harness, "_run_evaluation") as run_evaluation,
            ):
                with self.assertRaisesRegex(RuntimeError, "One or more conversations failed"):
                    await harness.main_async(args)

        self.assertEqual(write_results.call_args.args[0], [partial_result])
        run_evaluation.assert_not_called()
        simulator_config = configure_session.await_args.args[1]
        self.assertEqual(simulator_config.vad_type, args.vad_type)
        self.assertEqual(simulator_config.noise_reduction, args.noise_reduction)
        self.assertFalse(simulator_config.enable_barge_in)
        self.assertIsNone(simulator_config.agent_name)


if __name__ == "__main__":
    unittest.main()