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
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from itertools import groupby
from operator import attrgetter

from azure.identity import DefaultAzureCredential

from .config import SessionConfig, DEFAULT_SESSION_CONFIG
from .voicelive_client import VoiceLiveClient, ConversationTurn, sanitize_text_for_utf8
from .storage import BlobStorageClient, DatasetEntry
from .jobs import job_manager, JobStatus

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
            if ".blob.core.windows.net" in data or ".blob.storage.azure.net" in data:
                try:
                    from azure.storage.blob import BlobClient
                    blob_client = BlobClient.from_blob_url(data, credential=DefaultAzureCredential())
                    with open(dest, "wb") as fout:
                        fout.write(blob_client.download_blob().readall())
                    logger.info(f"Downloaded blob audio ({os.path.getsize(dest)} bytes) → {dest}")
                    return os.path.abspath(dest)
                except Exception as exc:
                    logger.debug(f"BlobClient auth failed ({exc}), trying anonymous HTTP")
            resp = requests.get(data, timeout=120)
            resp.raise_for_status()
            with open(dest, "wb") as fout:
                fout.write(resp.content)
            logger.info(f"Downloaded media audio ({len(resp.content)} bytes) → {dest}")
            return os.path.abspath(dest)
        except Exception as exc:
            logger.error(f"Failed to download media audio from URL: {exc}")
            return None

    # Base64 data URI
    if data.startswith("data:"):
        try:
            _, encoded = data.split(",", 1)
        except ValueError:
            logger.error("Malformed base64 data-URI")
            return None
        try:
            raw_bytes = base64.b64decode(encoded)
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


async def process_conversation(
    entries: List[DatasetEntry],
    client: VoiceLiveClient,
    config: SessionConfig,
    storage: BlobStorageClient,
    temp_dir: str,
    job_id: str,
    conversation_id: str,
    dataset_base_path: str = "",
    on_file_complete: Optional[Callable] = None
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
    
    # Configure session (may include conversation-specific settings)
    conversation_config = config
    if entries and entries[0].system_prompt:
        # Override instructions from dataset
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
    
    for i, entry in enumerate(entries):
        turn_number = i + 1
        
        # Update progress
        await job_manager.update_job_progress(
            job_id,
            current_file=entry.wav_path or "(media)",
            current_conversation=conversation_id
        )
        
        try:
            # Resolve audio: media reference (URL/base64) or legacy blob path
            if entry.audio_media_ref:
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
            
            # Fix #4: Inter-turn synchronization — brief pause between turns
            # to let late events settle before starting next audio file
            if i < len(entries) - 1:
                await asyncio.sleep(0.5)
            
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
            result["source_file"] = entry.wav_path or "(media)"
            
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
            
            # Fix #8: Only emit results that have meaningful content
            # (don't inflate failure counts with empty turns)
            if turn.user_transcription or turn.assistant_response or turn.tool_calls:
                results.append(result)
                logger.info(f"Processed turn {turn_number}: {audio_source_label}")
            else:
                logger.warning(
                    f"Turn {turn_number} ({audio_source_label}) produced no content "
                    f"(empty query, response, and no tool calls) — skipped"
                )
                # Still append with error marker for traceability
                result["error"] = "Empty turn: no transcription, response, or tool calls captured"
                results.append(result)
            if on_file_complete:
                await on_file_complete(success=True)
            
        except Exception as e:
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
    dataset_path: str,
    session_mode: str = "per-conversation",
    max_workers: int = 4,
    session_config: Optional[Dict[str, Any]] = None
) -> None:
    """
    Process a complete dataset through VoiceLive.
    
    This is the main entry point for job processing.
    
    Args:
        job_id: Unique job identifier
        dataset_path: Path to dataset in blob storage
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
        
        # Download and parse dataset
        local_dataset_path, entries, blob_name = storage.download_dataset(dataset_path)
        
        # Extract base path from actual blob name for resolving relative audio paths
        # E.g., "Eiffel_Tower_Visit_1/Eiffel_Tower_Visit_1.jsonl" -> "Eiffel_Tower_Visit_1"
        dataset_base_path = ""
        if "/" in blob_name:
            dataset_base_path = "/".join(blob_name.split("/")[:-1])
        elif "\\" in blob_name:
            dataset_base_path = "\\".join(blob_name.split("\\")[:-1])
        logger.info(f"Dataset base path: {dataset_base_path}")
        
        # Filter to entries with audio
        audio_entries = [e for e in entries if e.has_audio()]
        if not audio_entries:
            raise ValueError("Dataset contains no audio files (WavPath field required)")
        
        # Update progress with total
        await job_manager.update_job_progress(job_id, total_files=len(audio_entries))
        
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
        
        logger.info(f"Processing {len(audio_entries)} files in {len(groups)} conversation(s)")
        
        # Create temp directory
        temp_dir = tempfile.mkdtemp(prefix=f"voicelive_{job_id}_")
        
        all_results = []
        files_processed = 0
        files_failed = 0
        
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
        
        # Process conversations (with concurrency limit for future parallel support)
        # Currently processing sequentially to maintain conversation context
        for conversation_id, conversation_entries in groups:
            try:
                async with VoiceLiveClient(
                    endpoint=voicelive_endpoint,
                    model=voicelive_model
                ) as client:
                    results = await process_conversation(
                        entries=conversation_entries,
                        client=client,
                        config=config,
                        storage=storage,
                        temp_dir=temp_dir,
                        job_id=job_id,
                        conversation_id=conversation_id,
                        dataset_base_path=dataset_base_path,
                        on_file_complete=on_file_complete
                    )
                    
                    all_results.extend(results)
                    
            except Exception as e:
                logger.error(f"Error processing conversation {conversation_id}: {e}")
                files_failed += len(conversation_entries)
                await job_manager.update_job_progress(
                    job_id,
                    files_processed=files_processed,
                    files_failed=files_failed
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
        
        # Update job as completed
        await job_manager.update_job_status(
            job_id,
            JobStatus.COMPLETED,
            output_path=output_path,
            results_count=len(all_results)
        )
        
        logger.info(f"Job {job_id} completed: {files_processed} files, {len(all_results)} results")
        
    except Exception as e:
        logger.exception(f"Job {job_id} failed: {e}")
        await job_manager.update_job_status(
            job_id,
            JobStatus.FAILED,
            error=str(e)
        )


async def start_processing_job(
    dataset_path: str,
    session_mode: str = "per-conversation",
    max_workers: int = 4,
    session_config: Optional[Dict[str, Any]] = None
) -> str:
    """
    Start a new processing job.
    
    Args:
        dataset_path: Path to dataset in blob storage
        session_mode: How to group files
        max_workers: Maximum parallel workers
        session_config: Optional session configuration
        
    Returns:
        Job ID
    """
    # Check capacity
    if not job_manager.can_start_job():
        raise RuntimeError("Maximum concurrent jobs reached. Please wait for running jobs to complete.")
    
    # Create job
    job = await job_manager.create_job(
        dataset_path=dataset_path,
        session_mode=session_mode,
        max_workers=max_workers,
        session_config=session_config
    )
    
    # Start processing task
    task = asyncio.create_task(
        process_dataset(
            job_id=job.job_id,
            dataset_path=dataset_path,
            session_mode=session_mode,
            max_workers=max_workers,
            session_config=session_config
        )
    )
    
    await job_manager.set_job_task(job.job_id, task)
    
    return job.job_id
