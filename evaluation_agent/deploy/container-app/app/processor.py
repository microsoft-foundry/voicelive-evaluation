"""
VoiceLive Audio Processor - Core Processing Logic

Orchestrates the processing of audio files through VoiceLive.
"""

import os
import asyncio
import base64
import json
import logging
import secrets
import tempfile
import wave
import numpy as np
import requests
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from itertools import groupby
from operator import attrgetter

from azure.identity import DefaultAzureCredential

from .config import SessionConfig, DEFAULT_SESSION_CONFIG, ProcessorMode, VoiceConfig
from .voicelive_client import VoiceLiveClient, ConversationTurn, sanitize_text_for_utf8
from .storage import BlobStorageClient, DatasetEntry
from .jobs import job_manager, JobStatus
from .persona_simulation import (
    SimulationAssets,
    SimulationIncompleteError,
    build_simulator_instructions,
    simulation_assets_from_dict,
)

logger = logging.getLogger(__name__)


def load_audio_file(file_path: str, target_sample_rate: int = 24000) -> bytes:
    """
    Load audio file and convert to PCM16 bytes.
    
    Supports PCM (8/16/24/32-bit) and IEEE float32 WAVs.
    
    Args:
        file_path: Path to audio file
        target_sample_rate: Target sample rate (default 24kHz for VoiceLive)
        
    Returns:
        PCM16 audio bytes
    """
    import struct as _struct

    # Sanitize path to prevent path traversal
    file_path = os.path.realpath(file_path)

    try:
        with wave.open(file_path, 'rb') as wav:
            n_channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            raw_data = wav.readframes(wav.getnframes())

        if sample_width == 2:
            audio = np.frombuffer(raw_data, dtype=np.int16)
        elif sample_width == 1:
            audio = np.frombuffer(raw_data, dtype=np.uint8).astype(np.int16) * 256
        elif sample_width == 4:
            audio = np.frombuffer(raw_data, dtype=np.int32)
            audio = (audio >> 16).astype(np.int16)
        else:
            raise ValueError(f"Unsupported sample width: {sample_width}")

    except wave.Error:
        # IEEE float32 WAVs (format tag 3) — wave module can't read these
        with open(file_path, 'rb') as f:
            data = f.read()
        if data[:4] != b'RIFF' or data[8:12] != b'WAVE':
            raise ValueError(f"Not a valid WAV file: {file_path}")
        pos = 12
        sample_rate = n_channels = 0
        audio_data = b''
        while pos < len(data) - 8:
            chunk_id = data[pos:pos+4]
            chunk_size = _struct.unpack_from('<I', data, pos+4)[0]
            if chunk_id == b'fmt ':
                n_channels = _struct.unpack_from('<H', data, pos+10)[0]
                sample_rate = _struct.unpack_from('<I', data, pos+12)[0]
            elif chunk_id == b'data':
                audio_data = data[pos+8:pos+8+chunk_size]
            pos += 8 + chunk_size
        if not audio_data:
            raise ValueError(f"No audio data found in: {file_path}")
        float_audio = np.frombuffer(audio_data, dtype=np.float32)
        audio = np.clip(float_audio * 32767, -32768, 32767).astype(np.int16)

    # Convert to mono if stereo
    if n_channels == 2:
        audio = audio.reshape(-1, 2).mean(axis=1).astype(np.int16)
    
    # Resample if needed
    if sample_rate != target_sample_rate:
        duration = len(audio) / sample_rate
        target_length = int(duration * target_sample_rate)
        indices = np.linspace(0, len(audio) - 1, target_length)
        audio = np.interp(indices, np.arange(len(audio)), audio).astype(np.int16)
    
    return audio.tobytes()


def _redact_url_params(text: str) -> str:
    """Redact query parameters from URLs in error messages to prevent SAS token leakage."""
    import re
    return re.sub(r'(https?://[^\s?]+)\?[^\s"\']+', r'\1?[REDACTED]', str(text))


def _resolve_audio_from_media(
    audio_ref: Dict[str, str],
    cache_dir: Optional[str] = None,
) -> Optional[str]:
    """Resolve an ``input_audio`` media reference to a local WAV file.

    Supports URLs (with Azure blob auth) and base64 data URIs.
    Aligned with the evaluation harness implementation.
    """
    data = (audio_ref or {}).get("data", "")
    fmt = (audio_ref or {}).get("format", "wav")
    if not data:
        logger.warning("Empty media data in input_audio reference")
        return None

    target_dir = cache_dir or tempfile.mkdtemp(prefix="voicelive_media_")
    suffix = f".{fmt}" if fmt else ".wav"

    # URL download
    if data.startswith("http://") or data.startswith("https://"):
        try:
            dest = os.path.join(target_dir, f"media_download_{secrets.token_hex(4)}{suffix}")
            from urllib.parse import urlparse
            hostname = urlparse(data).hostname or ""
            if hostname.endswith(".blob.core.windows.net") or hostname.endswith(".blob.storage.azure.net"):
                try:
                    from azure.storage.blob import BlobClient
                    blob_client = BlobClient.from_blob_url(data, credential=DefaultAzureCredential())
                    with open(dest, "wb") as fout:
                        fout.write(blob_client.download_blob().readall())
                    logger.info(f"Downloaded blob audio ({os.path.getsize(dest)} bytes) → {dest}")
                    return os.path.abspath(dest)
                except Exception as exc:
                    logger.debug(f"BlobClient auth failed ({exc}), trying anonymous HTTP")
            # Only allow Azure blob URLs for security (prevent SSRF)
            logger.warning(f"Non-Azure-blob URL rejected for security: {_redact_url_params(data)}")
            return None
        except Exception as exc:
            logger.error(f"Failed to download media audio from URL: {_redact_url_params(str(exc))}")
            return None

    # Base64 data URI
    if data.startswith("data:"):
        try:
            _, encoded = data.split(",", 1)
        except ValueError:
            logger.error("Malformed base64 data-URI")
            return None
        try:
            raw_bytes = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            logger.error(f"Base64 decode failed: {exc}")
            return None
        dest = os.path.join(target_dir, f"media_b64_{secrets.token_hex(4)}{suffix}")
        with open(dest, "wb") as fout:
            fout.write(raw_bytes)
        logger.info(f"Decoded base64 data-URI ({len(raw_bytes)} bytes) → {dest}")
        return os.path.abspath(dest)

    logger.warning(f"Unrecognised media data format (length={len(data)})")
    return None


def _download_foundry_dataset(dataset_spec: str) -> str:
    """Download a dataset JSONL from Foundry Data Store to a local temp file.

    Args:
        dataset_spec: ``NAME`` or ``NAME:VERSION``.

    Returns:
        Path to the downloaded local JSONL file.
    """
    from azure.ai.projects import AIProjectClient
    from urllib.parse import urlparse

    project_endpoint = (
        os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
        or os.environ.get("PROJECT_ENDPOINT")
    )
    if not project_endpoint:
        raise ValueError("PROJECT_ENDPOINT env var required for foundry_dataset")

    parts = dataset_spec.split(":", 1)
    name = parts[0]
    version = parts[1] if len(parts) > 1 else None

    client = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
    )

    if not version:
        versions = list(client.datasets.list_versions(name=name))
        if not versions:
            raise ValueError(f"Foundry dataset '{name}' not found")
        version = str(max(int(v.version) for v in versions))
        logger.info(f"Resolved Foundry dataset '{name}' to version {version}")

    creds = client.datasets.get_credentials(name=name, version=version)
    blob_ref = creds.blob_reference
    if not blob_ref or not blob_ref.blob_uri:
        raise ValueError(f"No download URI for Foundry dataset '{name}' v{version}")
    if not blob_ref.credential or not blob_ref.credential.sas_uri:
        raise ValueError(f"No SAS credential for Foundry dataset '{name}' v{version}")

    parsed_blob = urlparse(blob_ref.blob_uri)
    blob_path_parts = parsed_blob.path.strip("/").split("/", 1)
    blob_prefix = blob_path_parts[1] if len(blob_path_parts) > 1 else ""

    from azure.storage.blob import ContainerClient
    container_client = ContainerClient.from_container_url(blob_ref.credential.sas_uri)
    file_parts = []
    for bp in container_client.list_blobs(name_starts_with=blob_prefix or None):
        data = container_client.download_blob(bp).readall()
        file_parts.append(data.decode("utf-8"))
    if not file_parts:
        raise ValueError(f"No blobs found in Foundry dataset '{name}' v{version}")

    dest = os.path.join(
        tempfile.mkdtemp(prefix="foundry_dataset_"),
        f"{name}_v{version}.jsonl",
    )
    dest = os.path.realpath(dest)
    with open(dest, "w", encoding="utf-8") as f:
        f.write("\n".join(file_parts))

    logger.info(f"Downloaded Foundry dataset '{name}' v{version} → {dest}")
    return dest


def _parse_jsonl_entries(local_path: str) -> List[DatasetEntry]:
    """Parse a local JSONL file into DatasetEntry objects."""
    import json as _json
    local_path = os.path.realpath(local_path)
    entries = []
    with open(local_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith(("#", "//")):
                try:
                    data = _json.loads(line)
                    entries.append(DatasetEntry.from_dict(data))
                except _json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON line: {e}")
    logger.info(f"Parsed {len(entries)} entries from {local_path}")
    return entries


async def process_conversation(
    entries: List[DatasetEntry],
    client: VoiceLiveClient,
    config: SessionConfig,
    storage: BlobStorageClient,
    temp_dir: str,
    job_id: str,
    conversation_id: str,
    dataset_base_path: str = "",
    on_file_complete: Optional[Callable] = None,
    simulation_assets: Optional[SimulationAssets] = None,
    simulator_client: Optional[VoiceLiveClient] = None,
    simulator_config: Optional[SessionConfig] = None,
) -> List[Dict[str, Any]]:
    """
    Process a single conversation (multiple audio turns).
    
    Args:
        entries: List of dataset entries for this conversation
        client: Connected VoiceLive client
        config: Session configuration
        storage: Blob storage client
        temp_dir: Temporary directory for audio files
        job_id: Job ID for progress updates
        conversation_id: Conversation identifier
        dataset_base_path: Base path for resolving relative audio paths
        on_file_complete: Callback(success: bool) called after each file for progress tracking
        
    Returns:
        List of evaluation-ready result entries
    """
    results = []
    conversation_history: List[Dict[str, Any]] = []
    work_entries = list(entries)

    if simulation_assets and len(work_entries) != 1:
        raise ValueError(
            "Simulation mode requires exactly one seed audio entry per conversation"
        )
    if simulation_assets and (simulator_client is None or simulator_config is None):
        raise ValueError("Simulation mode requires a configured simulator client")
    
    # Configure session (may include conversation-specific settings)
    conversation_config = config
    if not config.is_agent_mode:
        # Only set instructions in model mode — agent manages its own
        if entries and entries[0].system_prompt:
            conversation_config = SessionConfig.from_dict({
                **config.to_dict(),
                "instructions": entries[0].system_prompt
            })
    if entries and entries[0].tool_definitions:
        tool_defs = entries[0].tool_definitions
        # Normalize: ensure tools is always a list (dataset may have single dict)
        if isinstance(tool_defs, dict):
            tool_defs = [tool_defs]
        conversation_config.tools = tool_defs
    
    # System instructions for conversation-history format
    system_instructions = conversation_config.instructions or ""
    
    await client.configure_session(conversation_config)
    
    turn_limit = simulation_assets.max_turns if simulation_assets else len(work_entries)
    for i in range(turn_limit):
        if i >= len(work_entries):
            break
        entry = work_entries[i]
        turn_number = i + 1
        
        # Update progress
        await job_manager.update_job_progress(
            job_id,
            current_file=entry.wav_path or ("(simulated)" if entry.audio_bytes else "(media)"),
            current_conversation=conversation_id
        )
        
        try:
            # Resolve audio: media reference (URL/base64) or legacy blob path
            if entry.audio_bytes is not None:
                audio_data = entry.audio_bytes
                audio_source_label = "simulated-persona"
            elif entry.audio_media_ref:
                local_path = _resolve_audio_from_media(
                    entry.audio_media_ref, cache_dir=temp_dir,
                )
                if not local_path:
                    raise FileNotFoundError(
                        f"Failed to resolve media audio for turn {turn_number}"
                    )
                audio_source_label = f"media:{local_path}"
            else:
                # Legacy: resolve blob path and download
                wav_path = entry.wav_path
                if dataset_base_path and not wav_path.startswith(dataset_base_path):
                    wav_path = f"{dataset_base_path}/{wav_path}"
                local_path = storage.download_audio_file(wav_path, temp_dir)
                audio_source_label = entry.wav_path
            
            # Load audio
            if entry.audio_bytes is None:
                audio_data = load_audio_file(local_path, config.audio.sample_rate)
            logger.debug(f"Loaded audio: {audio_source_label} ({len(audio_data)} bytes)")
            
            # Process through VoiceLive
            turn = await client.process_audio(
                audio_data,
                ground_truth=entry.answer or "",
                tool_definitions=entry.tool_definitions or conversation_config.tool_definitions,
                push_to_talk=conversation_config.push_to_talk,
                sample_rate=config.audio.sample_rate
            )
            turn.turn_number = turn_number
            
            # Convert to evaluation format (conversation-history)
            result = turn.to_eval_format(
                ground_truth=entry.answer or "",
                tool_definitions=entry.tool_definitions or conversation_config.tool_definitions or [],
                question=entry.question or "",
                barge_in=entry.barge_in,
                system_instructions=system_instructions,
                conversation_history=conversation_history
            )
            
            # Add metadata
            result["conversation_id"] = conversation_id
            result["source_file"] = entry.wav_path or ("(simulated)" if entry.audio_bytes else "(media)")
            
            # Build history entry for subsequent turns (use transcription, not question)
            turn_messages = []
            user_text = sanitize_text_for_utf8(turn.user_transcription) if turn.user_transcription else ""
            if user_text:
                turn_messages.append({"role": "user", "content": [{"type": "text", "text": user_text}]})
            for tr in (turn.tool_results or []):
                args = tr.get("arguments", tr.get("args", {}))
                parsed_args = args if isinstance(args, dict) else json.loads(args) if isinstance(args, str) and args.strip() else {}
                turn_messages.append({
                    "role": "assistant",
                    "content": [{"type": "tool_call", "tool_call_id": tr["call_id"],
                                 "name": tr["name"], "arguments": parsed_args}],
                })
                turn_messages.append({
                    "role": "tool",
                    "tool_call_id": tr["call_id"],
                    "content": [{"type": "tool_result", "tool_result": tr["result"] or ""}],
                })
            if turn.assistant_response:
                turn_messages.append({"role": "assistant", "content": turn.assistant_response})
            conversation_history.append({"turn": turn_number, "messages": turn_messages})

            if turn.user_transcription or turn.assistant_response or turn.tool_calls:
                results.append(result)
                logger.info(f"Processed turn {turn_number}: {audio_source_label}")
            else:
                logger.warning(
                    f"Turn {turn_number} ({audio_source_label}) produced no content "
                    f"(empty query, response, and no tool calls) - skipped"
                )
                result["error"] = "Empty turn: no transcription, response, or tool calls captured"
                results.append(result)
            if on_file_complete:
                await on_file_complete(success=True)

            if simulation_assets and turn_number < turn_limit:
                assistant_audio = b"".join(turn.response_audio_chunks)
                if not assistant_audio:
                    raise SimulationIncompleteError(
                        f"Simulation incomplete after turn {turn_number}: "
                        "tested assistant returned no audio for the persona",
                        results.copy(),
                    )
                simulated_audio = b""
                simulated_text = ""
                for generation_attempt in range(1, 3):
                    simulated_turn = await simulator_client.process_audio(
                        assistant_audio,
                        push_to_talk=simulator_config.push_to_talk,
                        sample_rate=simulator_config.audio.sample_rate,
                    )
                    simulated_audio = b"".join(simulated_turn.response_audio_chunks)
                    simulated_text = simulated_turn.assistant_response
                    if simulated_audio:
                        break
                    logger.warning(
                        f"Turn {turn_number}: persona returned no audio "
                        f"(attempt {generation_attempt}/2)"
                    )
                    if generation_attempt < 2:
                        await asyncio.sleep(0.5)
                if not simulated_audio:
                    raise SimulationIncompleteError(
                        f"Simulation incomplete after turn {turn_number}: "
                        "persona returned no audio after 2 attempts",
                        results.copy(),
                    )
                work_entries.append(
                    DatasetEntry(
                        audio_bytes=simulated_audio,
                        question=simulated_text or None,
                        conversation_id=conversation_id,
                    )
                )

            if turn_number < turn_limit and i + 1 < len(work_entries):
                await asyncio.sleep(0.5)
            
        except Exception as e:
            if isinstance(e, SimulationIncompleteError):
                raise
            if simulation_assets:
                raise SimulationIncompleteError(
                    f"Simulation incomplete while processing turn {turn_number}: {e}",
                    results.copy(),
                ) from e
            source_label = audio_source_label if 'audio_source_label' in dir() else (entry.wav_path or "(media)")
            logger.error(f"Error processing {source_label}: {e}")
            results.append({
                "conversation_id": conversation_id,
                "source_file": entry.wav_path or "(media)",
                "error": str(e),
                "turn_number": turn_number
            })
            if on_file_complete:
                await on_file_complete(success=False)
    
    return results


async def process_dataset(
    job_id: str,
    dataset_path: Optional[str] = None,
    foundry_dataset: Optional[str] = None,
    session_mode: str = "per-conversation",
    max_workers: int = 4,
    session_config: Optional[Dict[str, Any]] = None,
    simulation_config: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Process a complete dataset through VoiceLive.
    
    This is the main entry point for job processing.
    
    Args:
        job_id: Unique job identifier
        dataset_path: Path to dataset in blob storage
        foundry_dataset: Foundry Data Store dataset (NAME or NAME:VERSION)
        session_mode: How to group files (per-conversation, per-file, single)
        max_workers: Maximum parallel conversations
        session_config: Optional session configuration override
    """
    try:
        await job_manager.update_job_status(job_id, JobStatus.RUNNING)
        
        # Initialize clients
        storage = BlobStorageClient()
        
        voicelive_endpoint = os.environ.get("AZURE_VOICELIVE_ENDPOINT")
        voicelive_model = os.environ.get("AZURE_VOICELIVE_MODEL", "gpt-realtime")
        
        if not voicelive_endpoint:
            raise ValueError("AZURE_VOICELIVE_ENDPOINT environment variable required")
        
        # Build config
        if session_config:
            config = SessionConfig.from_dict(session_config)
        else:
            config = DEFAULT_SESSION_CONFIG
        config.model = voicelive_model
        simulation_assets = (
            simulation_assets_from_dict(simulation_config)
            if simulation_config is not None
            else None
        )
        
        # Env var fallback for agent mode
        if not config.is_agent_mode:
            env_agent_name = os.environ.get("AGENT_NAME", "")
            env_project_name = os.environ.get("PROJECT_NAME", "")
            if env_agent_name and env_project_name:
                from .config import AgentConfig
                config.agent = AgentConfig(
                    agent_name=env_agent_name,
                    project_name=env_project_name,
                    agent_version=os.environ.get("AGENT_VERSION"),
                    foundry_resource_override=os.environ.get("FOUNDRY_RESOURCE_OVERRIDE"),
                    authentication_identity_client_id=os.environ.get("AGENT_AUTHENTICATION_IDENTITY_CLIENT_ID"),
                )
                config.mode = ProcessorMode.AGENT_MODE
                logger.info(f"Agent mode enabled via env vars: agent={env_agent_name}, project={env_project_name}")
        
        # Download and parse dataset from Foundry or blob
        if foundry_dataset:
            local_dataset_path = _download_foundry_dataset(foundry_dataset)
            entries = _parse_jsonl_entries(local_dataset_path)
            dataset_base_path = ""
            blob_name = f"foundry:{foundry_dataset}"
        else:
            local_dataset_path, entries, blob_name = storage.download_dataset(dataset_path)
            # Extract base path for resolving relative audio paths
            dataset_base_path = ""
            if "/" in blob_name:
                dataset_base_path = "/".join(blob_name.split("/")[:-1])
            elif "\\" in blob_name:
                dataset_base_path = "\\".join(blob_name.split("\\")[:-1])
        
        logger.info(f"Dataset base path: {dataset_base_path}")
        
        # Filter to entries with audio
        audio_entries = [e for e in entries if e.has_audio()]
        if not audio_entries:
            raise ValueError("Dataset contains no audio entries (WavPath or input_audio required)")
        
        # Update progress with total
        # Group entries based on session mode
        if session_mode == "per-conversation":
            # Group by conversation ID
            sorted_entries = sorted(audio_entries, key=lambda e: e.conversation_id or "default")
            groups = [
                (cid, list(group))
                for cid, group in groupby(sorted_entries, key=lambda e: e.conversation_id or "default")
            ]
        elif session_mode == "per-file":
            # Each file is its own conversation
            groups = [(f"file_{i}", [e]) for i, e in enumerate(audio_entries)]
        else:  # single
            # All files in one conversation
            groups = [("single", audio_entries)]

        if simulation_assets and any(len(group) != 1 for _, group in groups):
            raise ValueError(
                "Simulation mode requires exactly one seed audio entry per conversation"
            )

        expected_files = (
            len(groups) * simulation_assets.max_turns
            if simulation_assets
            else len(audio_entries)
        )
        await job_manager.update_job_progress(job_id, total_files=expected_files)
        
        logger.info(f"Processing {len(audio_entries)} files in {len(groups)} conversation(s)")
        
        # Create temp directory
        temp_dir = tempfile.mkdtemp(prefix=f"voicelive_{job_id}_")
        
        all_results = []
        files_processed = 0
        files_failed = 0
        conversation_failures = []
        
        async def on_file_complete(success: bool):
            """Update progress after each file is processed."""
            nonlocal files_processed, files_failed
            if success:
                files_processed += 1
            else:
                files_failed += 1
            await job_manager.update_job_progress(
                job_id,
                files_processed=files_processed,
                files_failed=files_failed
            )
        
        # Build credential once for all conversations
        credential = DefaultAzureCredential()
        
        # Process conversations (with concurrency limit for future parallel support)
        # Currently processing sequentially to maintain conversation context
        for conversation_id, conversation_entries in groups:
            processed_before_conversation = files_processed
            try:
                async with VoiceLiveClient.from_session_config(
                    endpoint=voicelive_endpoint,
                    config=config,
                    credential=credential
                ) as client:
                    if simulation_assets:
                        simulator_config = replace(
                            config,
                            instructions=build_simulator_instructions(simulation_assets),
                            model=simulation_assets.model,
                            voice=VoiceConfig(
                                name=simulation_assets.voice,
                                type=simulation_assets.voice_type,
                            ),
                            turn_detection=replace(
                                config.turn_detection,
                                enable_barge_in=False,
                            ),
                            tools=None,
                            tool_definitions=None,
                            mode=ProcessorMode.AUDIO_EVALUATION,
                            agent=None,
                        )
                        async with VoiceLiveClient(
                            endpoint=voicelive_endpoint,
                            model=simulation_assets.model,
                            credential=credential,
                        ) as simulator_client:
                            await simulator_client.configure_session(simulator_config)
                            results = await process_conversation(
                                entries=conversation_entries,
                                client=client,
                                config=config,
                                storage=storage,
                                temp_dir=temp_dir,
                                job_id=job_id,
                                conversation_id=conversation_id,
                                dataset_base_path=dataset_base_path,
                                on_file_complete=on_file_complete,
                                simulation_assets=simulation_assets,
                                simulator_client=simulator_client,
                                simulator_config=simulator_config,
                            )
                    else:
                        results = await process_conversation(
                            entries=conversation_entries,
                            client=client,
                            config=config,
                            storage=storage,
                            temp_dir=temp_dir,
                            job_id=job_id,
                            conversation_id=conversation_id,
                            dataset_base_path=dataset_base_path,
                            on_file_complete=on_file_complete,
                        )
                    
                    all_results.extend(results)
                    
            except SimulationIncompleteError as e:
                all_results.extend(e.partial_results)
                completed_turns = files_processed - processed_before_conversation
                files_failed += max(0, simulation_assets.max_turns - completed_turns)
                if simulation_assets:
                    conversation_failures.append(f"{conversation_id}: {e}")
                logger.error(f"Error processing conversation {conversation_id}: {e}")
                await job_manager.update_job_progress(
                    job_id,
                    files_processed=files_processed,
                    files_failed=files_failed,
                )
            except Exception as e:
                logger.error(f"Error processing conversation {conversation_id}: {e}")
                completed_turns = files_processed - processed_before_conversation
                target_turns = (
                    simulation_assets.max_turns if simulation_assets else len(conversation_entries)
                )
                files_failed += max(0, target_turns - completed_turns)
                if simulation_assets:
                    conversation_failures.append(f"{conversation_id}: {e}")
                await job_manager.update_job_progress(
                    job_id,
                    files_processed=files_processed,
                    files_failed=files_failed,
                )
        
        # Upload results
        output_path = storage.upload_results(
            job_id=job_id,
            results=all_results,
            metadata={
                "dataset_path": dataset_path,
                "session_mode": session_mode,
                "model": voicelive_model,
                "files_processed": files_processed,
                "files_failed": files_failed,
                "conversations": len(groups)
            }
        )
        
        # Clean up temp directory
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        
        final_status = JobStatus.FAILED if conversation_failures else JobStatus.COMPLETED
        await job_manager.update_job_status(
            job_id,
            final_status,
            error="; ".join(conversation_failures) or None,
            output_path=output_path,
            results_count=len(all_results),
        )
        
        logger.info(
            f"Job {job_id} {final_status.value}: "
            f"{files_processed} files, {len(all_results)} results"
        )
        
    except Exception as e:
        logger.exception(f"Job {job_id} failed: {e}")
        await job_manager.update_job_status(
            job_id,
            JobStatus.FAILED,
            error=str(e)
        )


async def start_processing_job(
    dataset_path: Optional[str] = None,
    foundry_dataset: Optional[str] = None,
    session_mode: str = "per-conversation",
    max_workers: int = 4,
    session_config: Optional[Dict[str, Any]] = None,
    simulation_config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Start a new processing job.
    
    Args:
        dataset_path: Path to dataset in blob storage
        foundry_dataset: Foundry Data Store dataset (NAME or NAME:VERSION)
        session_mode: How to group files
        max_workers: Maximum parallel workers
        session_config: Optional session configuration
        
    Returns:
        Job ID
    """
    # Check capacity
    if not job_manager.can_start_job():
        raise RuntimeError("Maximum concurrent jobs reached. Please wait for running jobs to complete.")
    
    effective_path = dataset_path or f"foundry:{foundry_dataset}"
    
    # Create job
    job = await job_manager.create_job(
        dataset_path=effective_path,
        session_mode=session_mode,
        max_workers=max_workers,
        session_config=session_config
    )
    
    # Start processing task
    task = asyncio.create_task(
        process_dataset(
            job_id=job.job_id,
            dataset_path=dataset_path,
            foundry_dataset=foundry_dataset,
            session_mode=session_mode,
            max_workers=max_workers,
            session_config=session_config,
            simulation_config=simulation_config,
        )
    )
    
    await job_manager.set_job_task(job.job_id, task)
    
    return job.job_id
