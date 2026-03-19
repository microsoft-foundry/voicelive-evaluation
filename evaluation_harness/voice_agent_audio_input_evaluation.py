"""
Voice Agent Audio Input Evaluation — Modern CLI Tool

Processes audio files through the Azure VoiceLive SDK for evaluation.
Uses async/await directly (no threading wrappers) with PTT/VAD mode support.
Patterns aligned with the container-app implementation.
"""

import os
import re
import json
import secrets
import sys
import wave
import base64
import logging
import argparse
import asyncio
import tempfile
import shutil
import numpy as np
import requests
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.voicelive.aio import connect as voicelive_connect
from azure.ai.voicelive.models import (
    ServerEventType,
    RequestSession,
    ServerVad,
    AzureSemanticVadMultilingual,
    AzureStandardVoice,
    OpenAIVoice,
    Modality,
    InputAudioFormat,
    OutputAudioFormat,
    AudioInputTranscriptionOptions,
    AudioNoiseReduction,
    AudioEchoCancellation,
    EouDetection,
    FunctionCallOutputItem,
    ItemType,
)

# Force UTF-8 encoding for stdout/stderr to handle international characters
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default system instruction
# ---------------------------------------------------------------------------
SYSTEM_INSTRUCTION = "You are a helpful agent assisting users with their questions."


# ---------------------------------------------------------------------------
# Eval naming helpers (aligned with evaluation agent naming)
# ---------------------------------------------------------------------------

def generate_harness_eval_group_name(config) -> str:
    """Generate eval group name from session config, matching agent naming pattern.
    Format: harness_{model}_{voice}_{vad}_{eod}
    """
    model = getattr(config, 'model', 'gpt-realtime') if hasattr(config, 'model') else config.get('model', 'gpt-realtime')
    voice = getattr(config, 'voice', 'alloy') if hasattr(config, 'voice') else config.get('voice', 'alloy')
    vad = getattr(config, 'vad_threshold', '0.5') if hasattr(config, 'vad_threshold') else config.get('vad_threshold', '0.5')
    eod = getattr(config, 'end_of_speech_timeout', '500') if hasattr(config, 'end_of_speech_timeout') else config.get('end_of_speech_timeout', '500')
    model_clean = str(model).replace("-", "").replace(".", "")
    return f"harness_{model_clean}_{voice}_{vad}_{eod}"


def generate_harness_run_name(dataset_name: str, dataset_version: str, evaluators: list) -> str:
    """Generate run name with metadata, matching agent naming pattern.
    Format: YYYYMMDD-HHMMSS-xxx | {dataset}_v{version} | {evaluator_summary}
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    random_suffix = secrets.token_hex(2)[:3]
    if not evaluators or len(evaluators) >= 10:
        eval_summary = "all"
    elif len(evaluators) >= 5:
        eval_summary = "default"
    else:
        eval_summary = "subset"
    dataset_base = os.path.splitext(os.path.basename(dataset_name))[0] if dataset_name else "dataset"
    return f"{timestamp}-{random_suffix} | {dataset_base}_v{dataset_version} | {eval_summary}"


def journal_harness_eval_group(
    eval_group_name: str,
    config,
    eval_group_id: str = "",
    output_dir: str = ".",
) -> None:
    """Record eval group -> config mapping in a local journal file.
    Writes to {output_dir}/eval_journal.jsonl (append mode).
    """
    journal_path = os.path.join(output_dir, "eval_journal.jsonl")
    entry = {
        "timestamp": datetime.now().isoformat(),
        "eval_group_name": eval_group_name,
        "eval_group_id": eval_group_id,
        "model": getattr(config, 'model', '') if config else '',
        "voice": getattr(config, 'voice', '') if config else '',
        "vad_threshold": str(getattr(config, 'vad_threshold', '')) if config else '',
        "end_of_speech_timeout": str(getattr(config, 'end_of_speech_timeout', '')) if config else '',
    }
    try:
        with open(journal_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')
        logger.info(f"Journaled eval group: {eval_group_name} -> {journal_path}")
    except Exception as e:
        logger.warning(f"Failed to journal eval group: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize_text_for_utf8(text: str) -> str:
    """Sanitize text to valid UTF-8, replacing smart quotes and control chars."""
    if not isinstance(text, str) or not text:
        return text or ""
    try:
        replacements = {
            '\u2018': "'", '\u2019': "'", '\u201A': "'", '\u201B': "'",
            '\u201C': '"', '\u201D': '"', '\u201E': '"', '\u201F': '"',
            '\u2013': '-', '\u2014': '-', '\u2015': '-',
            '\u2026': '...', '\u00A0': ' ',
        }
        for uc, asc in replacements.items():
            text = text.replace(uc, asc)
        text = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', text)
        text = text.replace('\ufffd', '').replace('\u0000', '')
        text = text.encode('utf-8', errors='replace').decode('utf-8')
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    except (UnicodeEncodeError, UnicodeDecodeError, AttributeError):
        try:
            return text.encode('ascii', errors='ignore').decode('ascii').strip()
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SessionConfig:
    """Configuration for a VoiceLive session.
    
    Aligned with Container App's SessionConfig for feature parity.
    Parameters can be set via CLI args or loaded from a JSON config file.
    Note: `instructions`, `tools`, and `tool_definitions` are set from dataset
    metadata, not via CLI or config file.
    """
    instructions: str = SYSTEM_INSTRUCTION
    model: str = "gpt-realtime"
    voice: str = "en-US-Ava:DragonHDLatestNeural"
    voice_type: str = "azure-standard"
    sample_rate: int = 24000
    push_to_talk: bool = False
    enable_barge_in: bool = True
    # Audio processing
    noise_reduction: str = "azure_deep_noise_suppression"
    echo_cancellation: str = "server_echo_cancellation"
    # Transcription
    transcription_model: Optional[str] = None  # Auto-set based on model if None
    # Turn detection (VAD)
    vad_type: str = "azure_semantic_vad_multilingual"
    vad_threshold: Optional[float] = None
    silence_duration_ms: Optional[int] = None
    # End-of-utterance detection
    use_eou_detection: bool = True
    eou_model: str = "semantic_detection_v1_multilingual"
    # Tools
    tools: Optional[List[Dict[str, Any]]] = None
    tool_definitions: Optional[List[Dict[str, Any]]] = None

    def get_transcription_model(self) -> str:
        """Return the appropriate transcription model for the configured model."""
        if self.transcription_model:
            return self.transcription_model
        if self.model == "gpt-realtime":
            return "gpt-4o-transcribe"
        elif self.model == "gpt-realtime-mini":
            return "gpt-4o-mini-transcribe"
        return "azure-speech"

    def supports_eou_detection(self) -> bool:
        """Check if the model supports end-of-utterance detection."""
        return self.model not in ("gpt-realtime", "gpt-realtime-mini")

    def get_final_instructions(self) -> str:
        """Return instructions with tool hint when tools are configured."""
        if self.tools:
            return f"{self.instructions} Use available tools when appropriate."
        return self.instructions


@dataclass
class ConversationTurn:
    """Data collected from a single conversation turn."""
    turn_number: int = 0
    user_transcription: str = ""
    assistant_response: str = ""
    assistant_audio_received: bool = False
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    response_audio_chunks: List[bytes] = field(default_factory=list)

    # Barge-in / auto-truncation
    was_truncated: bool = False
    response_full: str = ""  # Full response before truncation

    # Timing
    audio_send_end_time: Optional[datetime] = None
    transcription_complete_time: Optional[datetime] = None
    first_text_response_time: Optional[datetime] = None
    first_audio_response_time: Optional[datetime] = None

    def calculate_metrics(self) -> Dict[str, float]:
        """Calculate latency metrics for this turn."""
        metrics: Dict[str, float] = {}
        if self.audio_send_end_time:
            if self.transcription_complete_time:
                metrics["transcription_latency_seconds"] = (
                    self.transcription_complete_time - self.audio_send_end_time
                ).total_seconds()
            if self.first_text_response_time:
                metrics["text_response_latency_seconds"] = (
                    self.first_text_response_time - self.audio_send_end_time
                ).total_seconds()
            if self.first_audio_response_time:
                metrics["audio_response_latency_seconds"] = (
                    self.first_audio_response_time - self.audio_send_end_time
                ).total_seconds()
        return metrics


@dataclass
class DatasetEntry:
    """Parsed entry from a JSONL dataset file.

    Supports two audio source formats:
    - Legacy: ``audio_path`` points to a local WAV file (WavPath field).
    - Media:  ``audio_media_ref`` holds ``{"data": "<url_or_base64>", "format": "wav"}``
              from Foundry's ``input_audio`` content type.  Resolved to a temp
              file at processing time via ``_resolve_audio_from_media()``.
    """
    audio_path: Optional[str] = None
    audio_media_ref: Optional[Dict[str, str]] = None
    ground_truth: Optional[str] = None
    question: Optional[str] = None
    tool_definitions: Optional[List[Dict[str, Any]]] = None
    conversation_id: str = "default"
    system_prompt: Optional[str] = None
    barge_in: bool = False


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

def get_horoscope(sign: str) -> str:
    """Return a horoscope for the given zodiac sign."""
    return f"{sign}: Next Tuesday you will befriend a baby otter."


def fetchWeather(location: str) -> str:
    """Return a fake weather report for *location*."""
    return f"The weather in {location} is sunny with a high of 75°F."


TOOL_REGISTRY: Dict[str, Any] = {
    "get_horoscope": get_horoscope,
    "fetchWeather": fetchWeather,
    # Generic stubs from container app
    "get_weather": lambda **a: json.dumps({"temperature": 72, "condition": "sunny", "location": a.get("location", "unknown")}),
    "search": lambda **a: json.dumps({"results": [f"Result for: {a.get('query', '')}"]}),
    "get_time": lambda **a: json.dumps({"time": datetime.now().strftime("%H:%M"), "timezone": a.get("timezone", "UTC")}),
}


def execute_tool(name: str, args: dict) -> str:
    """Execute a tool by name and return the result string."""
    tool_fn = TOOL_REGISTRY.get(name)
    if tool_fn:
        try:
            if isinstance(args, dict) and "raw" not in args:
                return str(tool_fn(**args) if args else tool_fn())
            return f"[{name}: {args}]"
        except Exception as e:
            return f"[Tool {name} error: {e}]"
    return json.dumps({"error": f"Unknown tool: {name}", "status": "not_found"})


# ---------------------------------------------------------------------------
# Audio loading
# ---------------------------------------------------------------------------

def load_audio_file(path: str, target_rate: int = 24000) -> bytes:
    """Load a WAV file and return PCM16 bytes resampled to *target_rate*.

    Supports PCM (8/16/24/32-bit) and IEEE float32 WAVs.
    """
    import struct as _struct

    try:
        with wave.open(path, 'rb') as wf:
            sample_rate = wf.getframerate()
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            raw = wf.readframes(wf.getnframes())

        if sample_width == 2:
            audio = np.frombuffer(raw, dtype=np.int16)
        elif sample_width == 1:
            audio = np.frombuffer(raw, dtype=np.uint8).astype(np.int16) * 256
        elif sample_width == 4:
            audio = np.frombuffer(raw, dtype=np.int32)
            audio = (audio >> 16).astype(np.int16)
        else:
            raise ValueError(f"Unsupported sample width: {sample_width}")

    except wave.Error:
        # IEEE float32 WAVs (format tag 3) — wave module can't read these
        with open(path, 'rb') as f:
            data = f.read()
        # Parse RIFF header manually
        if data[:4] != b'RIFF' or data[8:12] != b'WAVE':
            raise ValueError(f"Not a valid WAV file: {path}")
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
            raise ValueError(f"No audio data found in: {path}")
        # Convert float32 samples to int16
        float_audio = np.frombuffer(audio_data, dtype=np.float32)
        audio = np.clip(float_audio * 32767, -32768, 32767).astype(np.int16)

    # Stereo → mono
    if n_channels == 2:
        audio = audio.reshape(-1, 2).mean(axis=1).astype(np.int16)

    # Resample
    if sample_rate != target_rate:
        duration = len(audio) / sample_rate
        target_length = int(duration * target_rate)
        indices = np.linspace(0, len(audio) - 1, target_length)
        audio = np.interp(indices, np.arange(len(audio)), audio).astype(np.int16)

    return audio.tobytes()


# ---------------------------------------------------------------------------
# Dataset reading
# ---------------------------------------------------------------------------

def read_dataset(path: str) -> List[DatasetEntry]:
    """Read a JSONL dataset file and return parsed entries.

    Supports three audio source formats:

    1. **Legacy (WavPath)** — ``{"WavPath": "file.wav", ...}``
    2. **Media in messages** — Foundry media dataset with ``input_audio``
       content parts inside a ``messages`` array.
    3. **Top-level media** — ``{"audio": {"type": "input_audio", ...}, ...}``
    """
    if not os.path.exists(path):
        logger.error(f"Dataset file not found: {path}")
        return []

    dataset_dir = os.path.dirname(os.path.abspath(path))
    entries: List[DatasetEntry] = []

    with open(path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning(f"Line {line_num}: JSON parse error: {e}")
                continue

            # --- Detect audio source format --------------------------------
            audio_path: Optional[str] = None
            audio_media_ref: Optional[Dict[str, str]] = None

            # 1. Check for input_audio inside messages (Foundry media format)
            media_ref = _extract_media_ref(record)
            if media_ref:
                audio_media_ref = media_ref
            else:
                # 2. Legacy WavPath / audio / audio_path field (strings only)
                raw_audio = record.get('audio')
                wav_path = (
                    record.get('WavPath')
                    or (raw_audio if isinstance(raw_audio, str) else None)
                    or record.get('audio_path')
                )
                if wav_path:
                    resolved = _resolve_audio_path(wav_path, dataset_dir)
                    if resolved:
                        audio_path = resolved
                    else:
                        logger.warning(f"Line {line_num}: audio file not found: {wav_path}")
                        continue

            if not audio_path and not audio_media_ref:
                logger.warning(f"Line {line_num}: no audio source found (WavPath or input_audio)")
                continue

            # --- Extract metadata ------------------------------------------
            tool_defs = record.get('tool_definitions', [])
            if isinstance(tool_defs, dict):
                tool_defs = [tool_defs]

            answer_raw = record.get('Answer') or record.get('answer') or record.get('expected_output')
            # Normalize list-type answers (e.g. speech-trivia-qa uses ["Paris", "City of Paris"])
            if isinstance(answer_raw, list):
                answer_raw = " OR ".join(str(a) for a in answer_raw if a) if answer_raw else None

            # Extract question from legacy field or from messages text parts
            question = record.get('Question') or record.get('question')
            if not question:
                question = _extract_text_from_messages(record)

            # Extract system prompt from legacy field or from messages
            system_prompt = record.get('system_prompt')
            if not system_prompt:
                system_prompt = _extract_system_prompt_from_messages(record)

            entries.append(DatasetEntry(
                audio_path=audio_path,
                audio_media_ref=audio_media_ref,
                ground_truth=answer_raw,
                question=question,
                tool_definitions=tool_defs if tool_defs else [],
                conversation_id=record.get('conversationID') or record.get('conversation_id') or 'default',
                system_prompt=system_prompt,
                barge_in=bool(record.get('barge_in', False)),
            ))

    media_count = sum(1 for e in entries if e.audio_media_ref)
    legacy_count = sum(1 for e in entries if e.audio_path)
    logger.info(f"Loaded {len(entries)} entries from {path} (legacy={legacy_count}, media={media_count})")
    return entries


def _extract_media_ref(record: dict) -> Optional[Dict[str, str]]:
    """Extract the first ``input_audio`` reference from a record.

    Checks both Foundry ``messages`` array and top-level ``audio`` field.
    """
    # Check inside messages array (Foundry media dataset format)
    for msg in record.get("messages", []):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", [])
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "input_audio":
                    ref = part.get("input_audio")
                    if ref and ref.get("data"):
                        return ref
    # Check top-level audio field (alternative format)
    top_audio = record.get("audio")
    if isinstance(top_audio, dict) and top_audio.get("type") == "input_audio":
        ref = top_audio.get("input_audio")
        if ref and ref.get("data"):
            return ref
    return None


def _extract_text_from_messages(record: dict) -> Optional[str]:
    """Extract user text from a Foundry messages array."""
    for msg in record.get("messages", []):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", [])
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [p.get("text", "") for p in content
                     if isinstance(p, dict) and p.get("type") == "text"]
            combined = " ".join(t for t in texts if t)
            if combined:
                return combined
    return None


def _extract_system_prompt_from_messages(record: dict) -> Optional[str]:
    """Extract system message content from a Foundry messages array."""
    for msg in record.get("messages", []):
        if msg.get("role") == "system":
            content = msg.get("content", "")
            return content if isinstance(content, str) else str(content)
    return None


def _resolve_audio_path(wav_path: str, dataset_dir: str) -> Optional[str]:
    """Try several strategies to locate an audio file.
    
    Validates that resolved path stays within the dataset directory
    or its parent tree (up to 5 levels) to prevent path traversal.
    """
    # Absolute path — validate it exists
    if os.path.isabs(wav_path) and os.path.exists(wav_path):
        return wav_path
    # Relative to dataset dir (basename)
    candidate = os.path.join(dataset_dir, os.path.basename(wav_path))
    if os.path.exists(candidate):
        return os.path.abspath(candidate)
    # Full relative from dataset dir
    candidate = os.path.join(dataset_dir, wav_path)
    if os.path.exists(candidate):
        resolved = os.path.abspath(candidate)
        # Validate resolved path is under dataset_dir (prevent traversal via ../)
        if os.path.commonpath([resolved, os.path.abspath(dataset_dir)]) == os.path.abspath(dataset_dir):
            return resolved
        logger.warning(f"Path traversal blocked: {wav_path} resolved outside dataset directory")
        return None
    # Walk up to 5 parent directories (path traversal check applied at each level)
    repo_root = os.path.abspath(dataset_dir)
    current = dataset_dir
    for _ in range(5):
        candidate = os.path.join(current, wav_path)
        if os.path.exists(candidate):
            resolved = os.path.abspath(candidate)
            # Validate resolved path stays within the search root (prevent traversal via ../)
            if os.path.commonpath([resolved, repo_root]) == repo_root:
                return resolved
            logger.warning(f"Path traversal blocked: {wav_path} resolved outside search root")
            return None
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def _resolve_audio_from_media(
    audio_ref: Dict[str, str],
    cache_dir: Optional[str] = None,
) -> Optional[str]:
    """Resolve an ``input_audio`` media reference to a local WAV file path.

    Supports two data forms:
    - **URL** (``https://...``)  — downloaded via ``requests``; Azure blob
      URLs are attempted with ``DefaultAzureCredential`` bearer token first.
    - **Base64 data-URI** (``data:audio/wav;base64,...``) — prefix stripped
      and decoded.  This is the Foundry Portal-compatible format.

    Args:
        audio_ref: ``{"data": "<url_or_base64>", "format": "wav"}``
        cache_dir: Directory for downloaded/decoded files.  A temp dir is
            created when *None*.

    Returns:
        Absolute path to the local WAV file, or *None* on failure.
    """
    data = (audio_ref or {}).get("data", "")
    fmt = (audio_ref or {}).get("format", "wav")
    if not data:
        logger.warning("Empty media data in input_audio reference")
        return None

    target_dir = cache_dir or tempfile.mkdtemp(prefix="voicelive_media_")
    suffix = f".{fmt}" if fmt else ".wav"

    # --- URL ---------------------------------------------------------------
    if data.startswith("http://") or data.startswith("https://"):
        try:
            dest = os.path.join(target_dir, f"media_download_{secrets.token_hex(4)}{suffix}")

            # Azure blob URLs — use BlobClient with DefaultAzureCredential
            from urllib.parse import urlparse
            hostname = urlparse(data).hostname or ""
            if hostname.endswith(".blob.core.windows.net") or hostname.endswith(".blob.storage.azure.net"):
                try:
                    from azure.storage.blob import BlobClient
                    blob_client = BlobClient.from_blob_url(data, credential=DefaultAzureCredential())
                    with open(dest, "wb") as fout:
                        download_stream = blob_client.download_blob()
                        fout.write(download_stream.readall())
                    file_size = os.path.getsize(dest)
                    logger.info(f"Downloaded blob audio ({file_size} bytes) → {dest}")
                    return os.path.abspath(dest)
                except Exception as exc:
                    logger.debug(f"BlobClient auth failed ({exc}), trying anonymous HTTP")

            # Non-Azure URLs or fallback — plain HTTP GET
            resp = requests.get(data, timeout=120)
            resp.raise_for_status()
            with open(dest, "wb") as fout:
                fout.write(resp.content)
            logger.info(f"Downloaded media audio ({len(resp.content)} bytes) → {dest}")
            return os.path.abspath(dest)
        except Exception as exc:
            logger.error(f"Failed to download media audio from URL: {exc}")
            return None

    # --- Base64 data-URI ---------------------------------------------------
    if data.startswith("data:"):
        # Strip "data:audio/wav;base64," prefix
        try:
            _, encoded = data.split(",", 1)
        except ValueError:
            logger.error("Malformed base64 data-URI (no comma separator)")
            return None
        try:
            raw_bytes = base64.b64decode(encoded)
        except Exception as exc:
            logger.error(f"Base64 decode failed for data-URI: {exc}")
            return None
        dest = os.path.join(target_dir, f"media_b64_{secrets.token_hex(4)}{suffix}")
        with open(dest, "wb") as fout:
            fout.write(raw_bytes)
        logger.info(f"Decoded base64 data-URI ({len(raw_bytes)} bytes) → {dest}")
        return os.path.abspath(dest)

    logger.warning(f"Unrecognised media data format (length={len(data)}). "
                   "Expected https:// URL or data: URI.")
    return None


# ---------------------------------------------------------------------------
# Session configuration
# ---------------------------------------------------------------------------

async def configure_session(connection: Any, config: SessionConfig) -> None:
    """Send a session.update to the VoiceLive connection."""
    # Voice
    if config.voice_type == "preset":
        sdk_voice = OpenAIVoice(name=config.voice)
    else:
        sdk_voice = AzureStandardVoice(name=config.voice, type=config.voice_type)

    # Turn detection — select VAD implementation based on vad_type
    vad_kwargs = {
        "auto_truncate": config.enable_barge_in,
        "interrupt_response": config.enable_barge_in,
    }
    if config.vad_threshold is not None:
        vad_kwargs["threshold"] = config.vad_threshold
    if config.silence_duration_ms is not None:
        vad_kwargs["silence_duration_ms"] = config.silence_duration_ms

    if config.vad_type == "server_vad":
        sdk_turn_detection = ServerVad(**vad_kwargs)
    else:
        # azure_semantic_vad_multilingual (default)
        if config.supports_eou_detection() and config.use_eou_detection:
            vad_kwargs["end_of_utterance_detection"] = EouDetection(model=config.eou_model)
        sdk_turn_detection = AzureSemanticVadMultilingual(**vad_kwargs)

    sdk_session = RequestSession(
        modalities=[Modality.TEXT, Modality.AUDIO],
        instructions=config.get_final_instructions(),
        voice=sdk_voice,
        turn_detection=sdk_turn_detection,
        input_audio_transcription=AudioInputTranscriptionOptions(model=config.get_transcription_model()),
        input_audio_noise_reduction=AudioNoiseReduction(type=config.noise_reduction),
        input_audio_echo_cancellation=AudioEchoCancellation(type=config.echo_cancellation),
        tools=config.tools if config.tools else None,
        input_audio_format=InputAudioFormat.PCM16,
        output_audio_format=OutputAudioFormat.PCM16,
        input_audio_sampling_rate=config.sample_rate,
    )
    await connection.session.update(session=sdk_session)
    logger.info(
        f"Session configured: model={config.model}, voice={config.voice}, "
        f"ptt={config.push_to_talk}, barge_in={config.enable_barge_in}, "
        f"vad={config.vad_type}, noise_reduction={config.noise_reduction}, "
        f"transcription={config.get_transcription_model()}"
    )


# ---------------------------------------------------------------------------
# Core audio processing (PTT / VAD)
# ---------------------------------------------------------------------------

async def process_audio(
    connection: Any,
    audio_data: bytes,
    config: SessionConfig,
    push_to_talk: bool,
    sample_rate: int = 24000,
    timeout_seconds: float = 120.0,
) -> ConversationTurn:
    """
    Send audio and collect the response.

    PTT mode: send all audio → commit → response.create → collect events.
    VAD mode: concurrent audio send + silence keepalive + event collection.
    """
    turn = ConversationTurn()

    chunk_samples = int(sample_rate * 0.02)
    chunk_bytes = chunk_samples * 2  # PCM16
    silence_chunk = base64.b64encode(b'\x00' * chunk_bytes).decode('utf-8')

    # ------------------------------------------------------------------
    # PTT: sequential send → commit → response.create, THEN collect
    # ------------------------------------------------------------------
    if push_to_talk:
        logger.info("PTT mode: sending audio synchronously before event collection")
        for i in range(0, len(audio_data), chunk_bytes):
            chunk = audio_data[i:i + chunk_bytes]
            encoded = base64.b64encode(chunk).decode('utf-8')
            await connection.input_audio_buffer.append(audio=encoded)
            await asyncio.sleep(0.02)
        turn.audio_send_end_time = datetime.now()
        await connection.input_audio_buffer.commit()
        await connection.response.create()
        logger.debug("Audio committed and response.create sent (PTT)")

    # ------------------------------------------------------------------
    # VAD: concurrent audio send + event collection
    # ------------------------------------------------------------------
    audio_send_complete = asyncio.Event()
    audio_task: Optional[asyncio.Task] = None
    silence_task: Optional[asyncio.Task] = None

    if not push_to_talk:
        async def send_audio() -> None:
            try:
                for i in range(0, len(audio_data), chunk_bytes):
                    chunk = audio_data[i:i + chunk_bytes]
                    encoded = base64.b64encode(chunk).decode('utf-8')
                    await connection.input_audio_buffer.append(audio=encoded)
                    await asyncio.sleep(0.02)
                turn.audio_send_end_time = datetime.now()
                logger.debug("Audio sent, starting silence keepalive for VAD")
            except Exception as e:
                logger.error(f"Audio send error: {e}")
            finally:
                audio_send_complete.set()

        async def send_silence() -> None:
            try:
                await audio_send_complete.wait()
                while True:
                    await connection.input_audio_buffer.append(audio=silence_chunk)
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug(f"Silence keepalive ended: {e}")

        audio_task = asyncio.create_task(send_audio())
        silence_task = asyncio.create_task(send_silence())

    # ------------------------------------------------------------------
    # Event collection
    # ------------------------------------------------------------------
    text_buffer = ""
    audio_transcript_buffer = ""
    pending_tool_call = None
    pending_tool_item_id: Optional[str] = None

    try:
        async with asyncio.timeout(timeout_seconds):
            logger.info(f"Collecting events (timeout={timeout_seconds}s, ptt={push_to_talk})")
            async for event in connection:
                etype = event.type

                if etype == ServerEventType.SESSION_CREATED:
                    logger.debug(f"Session: {getattr(event.session, 'id', None)}")

                elif etype == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
                    logger.debug("Speech started (VAD)")

                elif etype == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
                    turn.audio_send_end_time = datetime.now()
                    logger.debug("Speech stopped (VAD)")
                    if silence_task and not silence_task.done():
                        silence_task.cancel()
                        silence_task = None

                elif etype == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
                    turn.transcription_complete_time = datetime.now()
                    if hasattr(event, 'transcript'):
                        turn.user_transcription = event.transcript or ""
                    logger.debug(f"Transcription: {turn.user_transcription[:80]}")

                elif etype == ServerEventType.CONVERSATION_ITEM_CREATED:
                    if hasattr(event, 'item') and hasattr(event.item, 'type'):
                        if event.item.type == ItemType.FUNCTION_CALL:
                            pending_tool_item_id = event.item.id
                            logger.info(f"Function call item: {event.item.name} (id={event.item.id})")

                elif etype == ServerEventType.RESPONSE_TEXT_DELTA:
                    if turn.first_text_response_time is None:
                        turn.first_text_response_time = datetime.now()
                    if hasattr(event, 'delta') and event.delta:
                        text_buffer += event.delta

                elif etype == ServerEventType.RESPONSE_TEXT_DONE:
                    text = getattr(event, 'text', '') or text_buffer
                    if text and len(text) > len(turn.assistant_response):
                        turn.assistant_response = text
                    text_buffer = ""

                elif etype == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA:
                    if turn.first_text_response_time is None:
                        turn.first_text_response_time = datetime.now()
                    if hasattr(event, 'delta') and event.delta:
                        audio_transcript_buffer += event.delta

                elif etype == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
                    transcript = getattr(event, 'transcript', '') or audio_transcript_buffer
                    if transcript and len(transcript) > len(turn.assistant_response):
                        turn.assistant_response = transcript
                    audio_transcript_buffer = ""

                elif etype == ServerEventType.RESPONSE_AUDIO_DELTA:
                    if turn.first_audio_response_time is None:
                        turn.first_audio_response_time = datetime.now()
                        turn.assistant_audio_received = True
                    if hasattr(event, 'delta') and event.delta:
                        try:
                            chunk = event.delta if isinstance(event.delta, bytes) else bytes(event.delta)
                            turn.response_audio_chunks.append(chunk)
                            if len(turn.response_audio_chunks) % 50 == 1:
                                total = sum(len(c) for c in turn.response_audio_chunks)
                                logger.debug(f"Audio chunk #{len(turn.response_audio_chunks)}: {len(chunk)}B, total={total}B ({total/48000:.1f}s)")
                        except Exception as e:
                            logger.debug(f"Skipped malformed audio chunk: {e}")
                    else:
                        logger.debug(f"RESPONSE_AUDIO_DELTA with no delta: hasattr={hasattr(event, 'delta')}, delta_truthy={bool(getattr(event, 'delta', None))}")

                # Auto-truncation: user interrupted during agent playback
                elif etype == ServerEventType.CONVERSATION_ITEM_TRUNCATED:
                    turn.was_truncated = True
                    # Preserve full response before overwriting with truncated version
                    if turn.assistant_response and not turn.response_full:
                        turn.response_full = turn.assistant_response
                    content_index = getattr(event, 'content_index', None)
                    logger.info(f"Response truncated (barge-in): content_index={content_index}")
                    # Note: content_index is a content PART index (0,1,2...), not a character
                    # offset. The truncation is handled by VoiceLive's session context.
                    # We keep response_full for evaluation and note truncation in metadata.

                elif etype == ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
                    if hasattr(event, 'call_id') and hasattr(event, 'arguments'):
                        tc = {
                            "call_id": event.call_id,
                            "name": getattr(event, 'name', 'unknown'),
                            "arguments": event.arguments,
                        }
                        turn.tool_calls.append(tc)
                        logger.debug(f"Tool call: {tc['name']}({event.arguments[:100]})")
                        pending_tool_call = event

                elif etype == ServerEventType.RESPONSE_DONE:
                    logger.debug("response.done received")

                    # Execute pending tool call AFTER response.done
                    if pending_tool_call is not None:
                        logger.info("Executing pending tool call after response.done")
                        sent = await _execute_and_send_tool_result(
                            connection, pending_tool_call, turn, pending_tool_item_id
                        )
                        pending_tool_call = None
                        pending_tool_item_id = None
                        if sent:
                            continue  # wait for follow-up response

                    # Stop silence keepalive
                    if silence_task and not silence_task.done():
                        silence_task.cancel()
                        silence_task = None

                    # Drain late events
                    await _drain_late_events(connection, turn, audio_transcript_buffer, text_buffer)
                    break

                elif etype == ServerEventType.ERROR:
                    logger.error(f"VoiceLive error: {getattr(event, 'error', {})}")
                    break

                else:
                    logger.debug(f"Event: {etype}")

    except asyncio.TimeoutError:
        logger.warning(f"Response timeout after {timeout_seconds}s")
    finally:
        for t in (silence_task, audio_task):
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    # Fallback: use remaining buffer content
    if not turn.assistant_response:
        if audio_transcript_buffer:
            turn.assistant_response = audio_transcript_buffer
        elif text_buffer:
            turn.assistant_response = text_buffer

    logger.info(
        f"Turn done: query='{turn.user_transcription[:60]}', "
        f"response='{turn.assistant_response[:60]}', "
        f"tool_calls={len(turn.tool_calls)}"
    )
    return turn


async def _drain_late_events(
    connection: Any,
    turn: ConversationTurn,
    audio_transcript_buffer: str,
    text_buffer: str,
    drain_seconds: float = 5.0,
) -> None:
    """Wait briefly for late-arriving transcript and audio events after response.done."""
    late_audio = audio_transcript_buffer
    late_text = text_buffer
    late_audio_chunks = 0
    try:
        async with asyncio.timeout(drain_seconds):
            async for event in connection:
                etype = event.type
                if etype == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
                    turn.transcription_complete_time = datetime.now()
                    if hasattr(event, 'transcript') and event.transcript:
                        turn.user_transcription = event.transcript
                elif etype == ServerEventType.RESPONSE_AUDIO_DELTA:
                    if hasattr(event, 'delta') and event.delta:
                        try:
                            chunk = event.delta if isinstance(event.delta, bytes) else bytes(event.delta)
                            turn.response_audio_chunks.append(chunk)
                            late_audio_chunks += 1
                        except Exception as e:
                            logger.debug(f"Skipped malformed late audio chunk: {e}")
                elif etype == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA:
                    if hasattr(event, 'delta') and event.delta:
                        late_audio += event.delta
                elif etype == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
                    transcript = getattr(event, 'transcript', '') or late_audio
                    if transcript and len(transcript) > len(turn.assistant_response):
                        turn.assistant_response = transcript
                    late_audio = ""
                elif etype == ServerEventType.RESPONSE_TEXT_DELTA:
                    if hasattr(event, 'delta') and event.delta:
                        late_text += event.delta
                elif etype == ServerEventType.RESPONSE_TEXT_DONE:
                    text = getattr(event, 'text', '') or late_text
                    if text and len(text) > len(turn.assistant_response):
                        turn.assistant_response = text
                    late_text = ""
                elif etype in (ServerEventType.RESPONSE_DONE, ServerEventType.ERROR):
                    break
    except asyncio.TimeoutError:
        if late_audio and len(late_audio) > len(turn.assistant_response):
            turn.assistant_response = late_audio
        elif late_text and len(late_text) > len(turn.assistant_response):
            turn.assistant_response = late_text
        logger.debug("Post-response drain completed (timeout)")
    if late_audio_chunks > 0:
        logger.info(f"Captured {late_audio_chunks} late audio chunks in drain phase")


async def _execute_and_send_tool_result(
    connection: Any,
    event: Any,
    turn: ConversationTurn,
    previous_item_id: Optional[str] = None,
) -> bool:
    """Execute a tool call and send result back using FunctionCallOutputItem."""
    call_id = event.call_id
    name = getattr(event, 'name', 'unknown')
    args_str = event.arguments or ""

    try:
        args = json.loads(args_str) if args_str else {}
    except (json.JSONDecodeError, TypeError):
        args = {"raw": args_str}

    result_text = execute_tool(name, args)
    turn.tool_results.append({"call_id": call_id, "name": name, "result": result_text})

    try:
        fn_output = FunctionCallOutputItem(call_id=call_id, output=result_text)
        create_kwargs: Dict[str, Any] = {"item": fn_output}
        if previous_item_id:
            create_kwargs["previous_item_id"] = previous_item_id
        await connection.conversation.item.create(**create_kwargs)
        logger.info(f"Tool result sent: {name} -> {result_text[:100]}")
        await asyncio.sleep(0.05)
        await connection.response.create()
        return True
    except Exception as e:
        logger.error(f"Failed to send tool result: {e}")
        return False


# ---------------------------------------------------------------------------
# Conversation processing
# ---------------------------------------------------------------------------

def build_evaluation_data(
    turn: ConversationTurn,
    entry: DatasetEntry,
    conversation_history: List[Dict[str, Any]],
    system_instructions: str,
    tool_definitions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Build evaluation data in the format expected by voice_agent_evaluation.py
    and the Azure AI Evaluation SDK.

    The ``query`` field is a conversation-history list of role/content messages
    (system, then prior turns interleaved user/assistant/tool, then current
    user input).  ``response`` contains the current assistant messages.

    Query source priority:
      1. Ground-truth Question from input JSONL metadata (if present)
      2. VoiceLive real-time transcription (fallback)
    The VoiceLive transcription is always stored in ``transcript`` for WER evaluation.
    ``ground_truth_query_used`` indicates which source was used.
    """
    query_messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_instructions}
    ]

    # Prior turns (chronological)
    for hist in conversation_history:
        for msg in hist.get("messages", []):
            query_messages.append(msg)

    # Current turn — user input
    # Prefer ground-truth question from JSONL; fall back to VoiceLive transcription
    vl_transcript = sanitize_text_for_utf8(turn.user_transcription)
    gt_question = sanitize_text_for_utf8(entry.question) if entry.question else ""
    ground_truth_query_used = bool(gt_question)
    user_text = gt_question if ground_truth_query_used else vl_transcript

    if user_text:
        query_messages.append({"role": "user", "content": [{"type": "text", "text": user_text}]})

    # Current turn — tool messages (SDK-canonical flat format from break_tool_call_into_messages)
    for tr in turn.tool_results:
        args = tr.get("arguments", tr.get("args", {}))
        parsed_args = args if isinstance(args, dict) else json.loads(args) if isinstance(args, str) and args.strip() else {}
        query_messages.append({
            "role": "assistant",
            "content": [{"type": "tool_call", "tool_call_id": tr["call_id"],
                         "name": tr["name"], "arguments": parsed_args}],
        })
        query_messages.append({
            "role": "tool",
            "tool_call_id": tr["call_id"],
            "content": [{"type": "tool_result", "tool_result": tr["result"] or ""}],
        })

    # Build response list
    response_messages: List[Dict[str, Any]] = []
    resp_text = sanitize_text_for_utf8(turn.assistant_response)
    if resp_text:
        response_messages.append({
            "role": "assistant",
            "content": resp_text,
        })
    else:
        # Foundry rejects empty response lists — provide a descriptive placeholder
        reason = "barge-in truncated before response" if turn.was_truncated else "no response received"
        response_messages.append({
            "role": "assistant",
            "content": f"[No response — {reason}]",
        })

    metrics = turn.calculate_metrics()
    metrics["logical_turn_number"] = turn.turn_number
    metrics["audio_response_received"] = turn.assistant_audio_received

    return {
        "query": query_messages,
        "response": response_messages,
        "transcript": vl_transcript or "",
        "ground_truth_query_used": ground_truth_query_used,
        "barge_in": getattr(entry, 'barge_in', False),
        "was_truncated": turn.was_truncated,
        "response_full": sanitize_text_for_utf8(turn.response_full) if turn.response_full else "",
        "metrics": metrics,
        "tool_calls": turn.tool_calls or [],
        "tool_definitions": tool_definitions or [],
        "ground_truth": entry.ground_truth or "",
        "conversation_id": entry.conversation_id,
        "source_file": entry.audio_path or "(media)",
        "turn_number": turn.turn_number,
    }


async def process_conversation(
    entries: List[DatasetEntry],
    connection: Any,
    config: SessionConfig,
    output_dir: str,
    eval_output_file: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Process a multi-turn conversation through VoiceLive.

    Returns a list of evaluation-ready result dicts.
    If *eval_output_file* is provided, each turn is also appended to that
    JSONL file as it completes (for batch-processor compatibility).
    """
    results: List[Dict[str, Any]] = []
    conversation_history: List[Dict[str, Any]] = []

    # Override config from dataset if needed
    conv_config = config
    if entries and entries[0].system_prompt:
        from dataclasses import replace
        conv_config = replace(config, instructions=entries[0].system_prompt)
    if entries and entries[0].tool_definitions:
        from dataclasses import replace
        tool_defs = entries[0].tool_definitions
        if isinstance(tool_defs, dict):
            tool_defs = [tool_defs]
        conv_config = replace(conv_config, tools=tool_defs, tool_definitions=tool_defs)

    await configure_session(connection, conv_config)

    effective_tool_defs = conv_config.tool_definitions or []

    for i, entry in enumerate(entries):
        turn_number = i + 1
        try:
            # Resolve audio: media reference (URL/base64) or legacy file path
            if entry.audio_media_ref:
                local_path = _resolve_audio_from_media(
                    entry.audio_media_ref, cache_dir=output_dir,
                )
                if not local_path:
                    raise FileNotFoundError(
                        f"Failed to resolve media audio for turn {turn_number}"
                    )
                audio_source_label = f"media:{local_path}"
            else:
                local_path = entry.audio_path
                audio_source_label = entry.audio_path

            audio_data = load_audio_file(local_path, conv_config.sample_rate)
            logger.info(f"Loaded {audio_source_label} ({len(audio_data)} bytes)")

            turn = await process_audio(
                connection,
                audio_data,
                conv_config,
                push_to_talk=conv_config.push_to_talk,
                sample_rate=conv_config.sample_rate,
            )
            turn.turn_number = turn_number

            # Inter-turn pause
            if i < len(entries) - 1:
                await asyncio.sleep(0.5)

            result = build_evaluation_data(
                turn, entry, conversation_history,
                system_instructions=conv_config.instructions,
                tool_definitions=entry.tool_definitions or effective_tool_defs,
            )
            results.append(result)

            # Append to evaluation aggregate file (for batch processor)
            if eval_output_file:
                _append_jsonl(eval_output_file, result)

            # Save response audio as WAV
            if turn.response_audio_chunks:
                total_bytes = sum(len(c) for c in turn.response_audio_chunks)
                logger.info(f"Turn {turn.turn_number}: {len(turn.response_audio_chunks)} audio chunks, {total_bytes} bytes ({total_bytes/48000:.1f}s at 24kHz)")
                audio_out_dir = os.path.join(output_dir, entry.conversation_id)
                save_response_audio(turn, audio_out_dir, entry.conversation_id, conv_config.sample_rate)
            else:
                logger.warning(f"Turn {turn.turn_number}: NO audio chunks collected (audio_received={turn.assistant_audio_received})")

            # Update conversation history for subsequent turns
            turn_messages: List[Dict[str, Any]] = []
            user_text = sanitize_text_for_utf8(turn.user_transcription)
            if user_text:
                turn_messages.append({"role": "user", "content": [{"type": "text", "text": user_text}]})
            # Include tool call/result messages in SDK-canonical flat format
            for tr in turn.tool_results:
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
            resp_text = sanitize_text_for_utf8(turn.assistant_response)
            if resp_text:
                turn_messages.append({"role": "assistant", "content": resp_text})
            conversation_history.append({"turn": turn_number, "messages": turn_messages})

            logger.info(f"Turn {turn_number} done: {os.path.basename(audio_source_label)}")

        except Exception as e:
            source_label = entry.audio_path or "(media)"
            logger.error(f"Error processing {source_label}: {e}")
            results.append({
                "conversation_id": entry.conversation_id,
                "source_file": source_label,
                "error": str(e),
                "turn_number": turn_number,
            })

    return results


def _append_jsonl(path: str, record: Dict[str, Any]) -> None:
    """Append a single JSON record to a JSONL file.
    
    Note: Not safe for concurrent writes from multiple processes.
    For batch processing, use per-process files and aggregate after.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def save_response_audio(
    turn: ConversationTurn,
    output_dir: str,
    conversation_id: str,
    sample_rate: int = 24000,
) -> Optional[str]:
    """Save response audio chunks as a WAV file. Returns path or None."""
    if not turn.response_audio_chunks:
        return None
    os.makedirs(output_dir, exist_ok=True)
    filename = f"turn_{turn.turn_number:02d}_response.wav"
    wav_path = os.path.join(output_dir, filename)
    pcm_data = b"".join(turn.response_audio_chunks)
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit PCM
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    logger.info(f"Saved response audio: {wav_path} ({len(pcm_data)} bytes)")
    return wav_path


def write_results(results: List[Dict[str, Any]], output_dir: str, dataset_name: str) -> str:
    """Write results as a JSONL file and return the path."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(output_dir, f"{timestamp}_{dataset_name}.jsonl")
    with open(out_path, 'w', encoding='utf-8') as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    logger.info(f"Results written to {out_path} ({len(results)} entries)")
    return out_path


def write_operational_summary(
    results: List[Dict[str, Any]],
    output_dir: str,
    expected_turns: int,
    session_timestamp: str,
    session_suffix: Optional[str] = None,
    evaluation_enabled: bool = False,
) -> str:
    """Write operational_summary JSON matching the old prototype format."""
    actual_turns = len(results)
    audio_count = sum(
        1 for r in results
        if r.get("metrics", {}).get("audio_response_received", False)
    )
    text_only = sum(
        1 for r in results
        if not r.get("metrics", {}).get("audio_response_received", False)
        and r.get("response") and not r.get("error")
    )
    summary = {
        "operational_metrics": {
            "turns_processed": f"{actual_turns}/{expected_turns}",
            "expected_turns": expected_turns,
            "actual_turns": actual_turns,
            "vad_splitting_detected": actual_turns > expected_turns,
            "turn_expansion_factor": round(actual_turns / expected_turns, 2) if expected_turns > 0 else 0,
            "turns_with_audio_response": audio_count,
            "turns_with_text_only_response": text_only,
            "audio_response_rate": round(audio_count / actual_turns, 2) if actual_turns > 0 else 0,
        },
        "session_info": {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "evaluation_mode": "enabled" if evaluation_enabled else "disabled",
            "session_id": session_timestamp,
            "session_suffix": session_suffix or "",
        },
    }
    os.makedirs(output_dir, exist_ok=True)
    suffix_part = f"_{session_suffix}" if session_suffix else ""
    filename = f"operational_summary_{session_timestamp}{suffix_part}.json"
    out_path = os.path.join(output_dir, filename)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Operational summary written to {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Foundry Data Store integration
# ---------------------------------------------------------------------------

def download_foundry_dataset(dataset_spec: str) -> str:
    """Download a dataset JSONL from Foundry Data Store to a local temp file.

    Args:
        dataset_spec: ``NAME`` or ``NAME:VERSION``.  When version is omitted
            the latest version is resolved automatically.

    Returns:
        Path to the downloaded local JSONL file.

    Requires ``PROJECT_ENDPOINT`` environment variable.
    """
    from azure.ai.projects import AIProjectClient

    project_endpoint = (
        os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
        or os.environ.get("PROJECT_ENDPOINT")
    )
    if not project_endpoint:
        raise ValueError(
            "PROJECT_ENDPOINT env var required for --foundry-dataset"
        )

    parts = dataset_spec.split(":", 1)
    name = parts[0]
    version = parts[1] if len(parts) > 1 else None

    client = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
    )

    # Resolve latest version if not specified
    if not version:
        versions = list(client.datasets.list_versions(name=name))
        if not versions:
            raise ValueError(f"Foundry dataset '{name}' not found")
        version = str(max(int(v.version) for v in versions))
        logger.info(f"Resolved Foundry dataset '{name}' to version {version}")

    # Get SAS-authenticated download URL
    creds = client.datasets.get_credentials(name=name, version=version)
    creds_dict = creds.as_dict()
    blob_ref = (
        creds_dict.get("blobReferenceForConsumption")
        or creds_dict.get("blobReference", {})
    )
    blob_uri = blob_ref.get("blobUri")
    sas_uri = blob_ref.get("credential", {}).get("sasUri", "")

    if not blob_uri:
        raise ValueError(
            f"Could not get download URI for Foundry dataset '{name}' v{version}"
        )

    # Build download URL: blob URI + SAS token from container SAS
    if sas_uri and "?" in sas_uri:
        sas_token = sas_uri.split("?", 1)[1]
        download_url = f"{blob_uri}?{sas_token}"
    else:
        download_url = blob_uri

    resp = requests.get(download_url, timeout=120)
    resp.raise_for_status()

    # Write to temp file
    dest = os.path.join(
        tempfile.mkdtemp(prefix="foundry_dataset_"),
        f"{name}_v{version}.jsonl",
    )
    with open(dest, "w", encoding="utf-8") as f:
        f.write(resp.text)

    logger.info(
        f"Downloaded Foundry dataset '{name}' v{version} "
        f"({len(resp.text)} bytes) → {dest}"
    )
    return dest


def upload_dataset_to_foundry(
    file_path: str,
    name_prefix: str = "harness",
) -> str:
    """Upload a local JSONL file to Foundry Data Store.

    Auto-names the dataset ``{name_prefix}_{basename}`` and auto-versions
    (increments from latest existing version or starts at 1).

    Returns:
        The Foundry dataset ID (``azureai://...``).
    """
    from azure.ai.projects import AIProjectClient

    project_endpoint = (
        os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
        or os.environ.get("PROJECT_ENDPOINT")
    )
    if not project_endpoint:
        raise ValueError(
            "PROJECT_ENDPOINT env var required for --upload-dataset"
        )

    client = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
    )

    basename = os.path.splitext(os.path.basename(file_path))[0]
    dataset_name = f"{name_prefix}_{basename}"

    # Auto-version: find latest existing version and increment
    try:
        versions = list(client.datasets.list_versions(name=dataset_name))
        next_version = str(max(int(v.version) for v in versions) + 1)
    except Exception:
        next_version = "1"

    result = client.datasets.upload_file(
        name=dataset_name,
        version=next_version,
        file_path=file_path,
    )

    logger.info(
        f"Uploaded dataset to Foundry: {result.name} v{result.version} "
        f"(id={result.id})"
    )
    return result.id


# ---------------------------------------------------------------------------
# Async entry point
# ---------------------------------------------------------------------------

async def main_async(args: argparse.Namespace) -> None:
    """Async entry point — connect to VoiceLive, process dataset, write results."""
    # Support both old and new env var names
    endpoint = (
        os.environ.get("AZURE_VOICELIVE_ENDPOINT")
        or os.environ.get("AZURE_VOICE_LIVE_ENDPOINT")
        or ""
    )
    # CLI --model takes priority when explicitly provided
    env_model = (
        os.environ.get("AZURE_VOICELIVE_MODEL")
        or os.environ.get("AZURE_VOICE_LIVE_MODEL")
    )
    if "--model" in sys.argv:
        model = args.model  # User explicitly set --model
    else:
        model = env_model or args.model  # Env var or argparse default
    if not endpoint:
        raise ValueError(
            "AZURE_VOICELIVE_ENDPOINT (or AZURE_VOICE_LIVE_ENDPOINT) environment variable is required"
        )

    # Parse dataset
    all_entries = read_dataset(args.test_files_path)
    if not all_entries:
        logger.error("No entries found in dataset — exiting")
        return

    config = SessionConfig(
        model=model,
        voice=args.voice,
        voice_type=getattr(args, 'voice_type', 'azure-standard'),
        sample_rate=args.sample_rate,
        push_to_talk=args.push_to_talk,
        enable_barge_in=getattr(args, 'enable_barge_in', True),
        noise_reduction=getattr(args, 'noise_reduction', 'azure_deep_noise_suppression'),
        echo_cancellation=getattr(args, 'echo_cancellation', 'server_echo_cancellation'),
        transcription_model=getattr(args, 'transcription_model', None),
        vad_type=getattr(args, 'vad_type', 'azure_semantic_vad_multilingual'),
        vad_threshold=getattr(args, 'vad_threshold', None),
        silence_duration_ms=getattr(args, 'silence_duration_ms', None),
        use_eou_detection=getattr(args, 'use_eou_detection', True),
        eou_model=getattr(args, 'eou_model', 'semantic_detection_v1_multilingual'),
    )

    # Evaluation output file — aggregate file (batch mode) or auto-generated
    eval_dir = getattr(args, "evaluation_dir", None) or args.output_dir
    os.makedirs(eval_dir, exist_ok=True)
    dataset_name = os.path.splitext(os.path.basename(args.test_files_path))[0]
    aggregate_eval_file = getattr(args, "aggregate_eval_file", None)
    eval_output_file = aggregate_eval_file  # may be None

    # Group by session mode
    if args.session_mode == "per-conversation":
        groups: Dict[str, List[DatasetEntry]] = {}
        for e in all_entries:
            groups.setdefault(e.conversation_id, []).append(e)
        conversation_groups = list(groups.items())
    elif args.session_mode == "per-file":
        conversation_groups = [(f"file-{i}", [e]) for i, e in enumerate(all_entries, 1)]
    else:  # single
        conversation_groups = [("single", all_entries)]

    logger.info(f"Processing {len(all_entries)} files in {len(conversation_groups)} conversation(s)")

    all_results: List[Dict[str, Any]] = []
    credential = DefaultAzureCredential()
    api_version = (
        os.environ.get("AZURE_VOICELIVE_API_VERSION")
        or os.environ.get("AZURE_VOICE_LIVE_API_VERSION")
    )

    for conv_id, entries in conversation_groups:
        logger.info(f"Conversation '{conv_id}': {len(entries)} turn(s)")
        connect_kwargs: Dict[str, Any] = {
            "endpoint": endpoint,
            "credential": credential,
            "model": model,
        }
        if api_version:
            connect_kwargs["api_version"] = api_version

        async with voicelive_connect(**connect_kwargs) as connection:
            results = await process_conversation(
                entries, connection, config, args.output_dir,
                eval_output_file=eval_output_file,
            )
            all_results.extend(results)

    # Session naming
    session_suffix = getattr(args, "session_suffix", None)
    session_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    suffix_part = f"_{session_suffix}" if session_suffix else ""

    # Write raw JSONL output
    out_path = write_results(all_results, args.output_dir, dataset_name)

    # Write evaluation JSONL if not already written via aggregate file
    evaluation_enabled = bool(eval_dir)
    if not aggregate_eval_file:
        eval_filename = f"{session_timestamp}{suffix_part}_{dataset_name}.jsonl"
        eval_output_file = os.path.join(eval_dir, eval_filename)
        with open(eval_output_file, "w", encoding="utf-8") as f:
            for r in all_results:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        logger.info(f"Evaluation data written to {eval_output_file}")

    # Write operational summary
    write_operational_summary(
        all_results,
        output_dir=eval_dir,
        expected_turns=len(all_entries),
        session_timestamp=session_timestamp,
        session_suffix=session_suffix,
        evaluation_enabled=evaluation_enabled,
    )

    # Run evaluation if enabled and not in batch aggregation mode
    skip_eval = getattr(args, "skip_evaluation", False)
    evaluators = getattr(args, "evaluators", None)
    if not skip_eval and not aggregate_eval_file and eval_output_file:
        _run_evaluation(eval_output_file, args.output_dir,
                        eval_object_id=getattr(args, "eval_object_id", None),
                        evaluators=evaluators,
                        session_config=config)

    logger.info(f"Done — {len(all_results)} results written to {out_path}")

    # Upload to Foundry if requested
    if getattr(args, "upload_dataset", False) and eval_output_file:
        try:
            upload_dataset_to_foundry(eval_output_file, name_prefix="harness")
        except Exception as exc:
            logger.error(f"Foundry upload failed: {exc}")


# Default evaluators — aligned with Container App's DEFAULT_EVALUATORS
DEFAULT_EVALUATORS = [
    "intent_resolution",
    "task_adherence",
    "task_completion",
    "response_completeness",
    "tool_call_accuracy",
    "tool_selection",
    "tool_input_accuracy",
    "tool_output_utilization",
]

# Additional evaluators available but not in default set
ADDITIONAL_EVALUATORS = [
    "groundedness",
    "relevance",
    "tool_call_success",
    "fluency",
    "coherence",
]

ALL_EVALUATORS = DEFAULT_EVALUATORS + ADDITIONAL_EVALUATORS


def _run_evaluation(
    eval_input_path: str,
    output_dir: str,
    eval_object_id: Optional[str] = None,
    evaluators: Optional[str] = None,
    session_config=None,
) -> None:
    """Run voice_agent_evaluation.main() if the module is available."""
    try:
        import voice_agent_evaluation  # type: ignore
    except ImportError:
        logger.warning("voice_agent_evaluation module not found — skipping evaluation run")
        return
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        eval_name = os.path.basename(eval_input_path)
        eval_desc = generate_harness_eval_group_name(session_config) if session_config else f"harness_default_{ts}"
        eval_output = os.path.join(output_dir, ts)
        os.makedirs(eval_output, exist_ok=True)

        # Resolve evaluator list
        if evaluators == "all":
            eval_list = ALL_EVALUATORS
        elif evaluators and evaluators != "default":
            eval_list = [e.strip() for e in evaluators.split(",") if e.strip()]
            if not eval_list:
                logger.warning("Empty evaluator list after parsing — falling back to defaults")
                eval_list = DEFAULT_EVALUATORS
        else:
            eval_list = DEFAULT_EVALUATORS  # "default" → 8 defaults

        eval_run_name = generate_harness_run_name(eval_name, "1", eval_list)

        logger.info(f"Starting evaluation: {eval_name} (evaluators: {eval_list or 'default'})")
        voice_agent_evaluation.main(
            eval_input_path,
            referenceTranscriptFilePath="",
            output_folder=eval_output,
            eval_group_name=eval_desc,
            eval_object_id=eval_object_id or "",
            eval_run_name=eval_run_name,
            eval_run_scenario=eval_name,
            dataset_id="",
            dataset_appendix="",
            setupCustomEvaluators=False,
            evaluators=eval_list,
        )
        logger.info(f"Evaluation completed (results in {eval_output})")

        # Journal the eval group mapping
        journal_harness_eval_group(
            eval_group_name=eval_desc,
            config=session_config,
            output_dir=output_dir,
        )
    except Exception as e:
        logger.error(f"Evaluation failed: {e}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse arguments and run."""
    # Save original CWD so user-provided relative paths resolve correctly
    original_cwd = os.getcwd()
    script_dir = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(
        description="Process audio files through the Azure VoiceLive SDK for evaluation"
    )
    parser.add_argument(
        '--test-files', '-f', dest='test_files_path', default=None,
        help='JSONL file listing audio files and metadata',
    )
    parser.add_argument(
        '--foundry-dataset', dest='foundry_dataset', default=None,
        help='Read dataset from Foundry Data Store: NAME[:VERSION] (requires PROJECT_ENDPOINT)',
    )
    parser.add_argument(
        '--upload-dataset', dest='upload_dataset', action='store_true',
        help='Upload evaluation-ready dataset to Foundry after processing',
    )
    parser.add_argument(
        '--output-dir', '-o', dest='output_dir', default='output',
        help='Output directory (default: output/)',
    )
    parser.add_argument(
        '--evaluation-dir', '-e', dest='evaluation_dir', default=None,
        help='Evaluation data directory (default: same as output_dir)',
    )
    parser.add_argument(
        '--aggregate-eval-file', dest='aggregate_eval_file', default=None,
        help='Path to aggregate evaluation JSONL file (used by batch_processor)',
    )
    parser.add_argument(
        '--session-suffix', dest='session_suffix', default=None,
        help='Session suffix for output naming (used by batch_processor)',
    )
    parser.add_argument(
        '--eval-object-id', dest='eval_object_id', default=None,
        help='Existing evaluation object ID to reuse',
    )
    parser.add_argument(
        '--skip-evaluation', dest='skip_evaluation', action='store_true',
        help='Skip running evaluation after processing (useful in batch mode)',
    )
    parser.add_argument(
        '--session-mode', dest='session_mode',
        choices=['single', 'per-file', 'per-conversation'], default='per-conversation',
        help='Session handling mode (default: per-conversation)',
    )
    parser.add_argument(
        '--push-to-talk', dest='push_to_talk', action='store_true',
        help='Enable push-to-talk mode (default: VAD)',
    )
    parser.add_argument(
        '--enable-barge-in', dest='enable_barge_in', action='store_true', default=True,
        help='Enable auto-truncation for barge-in support (default: enabled)',
    )
    parser.add_argument(
        '--disable-barge-in', dest='enable_barge_in', action='store_false',
        help='Disable auto-truncation for barge-in support',
    )
    parser.add_argument(
        '--model', default='gpt-realtime',
        help='VoiceLive model (default: gpt-realtime)',
    )
    parser.add_argument(
        '--voice', default='en-US-Ava:DragonHDLatestNeural',
        help='Voice name (default: en-US-Ava:DragonHDLatestNeural)',
    )
    parser.add_argument(
        '--voice-type', dest='voice_type', default='azure-standard',
        help='Voice type: azure-standard or preset (default: azure-standard)',
    )
    parser.add_argument(
        '--sample-rate', dest='sample_rate', type=int, default=24000,
        help='Audio sample rate in Hz (default: 24000)',
    )
    # Audio processing
    parser.add_argument(
        '--noise-reduction', dest='noise_reduction', default='azure_deep_noise_suppression',
        help='Noise reduction type (default: azure_deep_noise_suppression)',
    )
    parser.add_argument(
        '--echo-cancellation', dest='echo_cancellation', default='server_echo_cancellation',
        help='Echo cancellation type (default: server_echo_cancellation)',
    )
    parser.add_argument(
        '--transcription-model', dest='transcription_model', default=None,
        help='Transcription model override (default: auto based on model)',
    )
    # Turn detection (VAD)
    parser.add_argument(
        '--vad-type', dest='vad_type', default='azure_semantic_vad_multilingual',
        help='VAD type (default: azure_semantic_vad_multilingual)',
    )
    parser.add_argument(
        '--vad-threshold', dest='vad_threshold', type=float, default=None,
        help='VAD threshold (default: SDK default)',
    )
    parser.add_argument(
        '--silence-duration-ms', dest='silence_duration_ms', type=int, default=None,
        help='Silence duration in ms for VAD (default: SDK default)',
    )
    # End-of-utterance detection
    parser.add_argument(
        '--enable-eou-detection', dest='use_eou_detection', action='store_true', default=True,
        help='Enable end-of-utterance detection (default: enabled)',
    )
    parser.add_argument(
        '--disable-eou-detection', dest='use_eou_detection', action='store_false',
        help='Disable end-of-utterance detection',
    )
    parser.add_argument(
        '--eou-model', dest='eou_model', default='semantic_detection_v1_multilingual',
        help='EOU detection model (default: semantic_detection_v1_multilingual)',
    )
    # Config file
    parser.add_argument(
        '--config', dest='config_file', default=None,
        help='Load session config from a JSON file (CLI args override file values)',
    )
    # Evaluators
    parser.add_argument(
        '--evaluators', dest='evaluators', default='default',
        help='Evaluator selection: "default" (8 evaluators), "all" (13), or comma-separated list',
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Enable DEBUG logging',
    )
    args = parser.parse_args()

    # Validate: one of --test-files or --foundry-dataset is required
    if not args.test_files_path and not args.foundry_dataset:
        parser.error("one of --test-files/-f or --foundry-dataset is required")

    # Resolve Foundry dataset to local file
    _foundry_temp_dir = None
    if args.foundry_dataset:
        # Need .env loaded early for PROJECT_ENDPOINT
        load_dotenv(os.path.join(script_dir, ".env"), override=True)
        args.test_files_path = download_foundry_dataset(args.foundry_dataset)
        _foundry_temp_dir = os.path.dirname(args.test_files_path)

    # Load config file if specified (CLI args override)
    if args.config_file:
        config_path = args.config_file
        if not os.path.isabs(config_path):
            config_path = os.path.normpath(os.path.join(original_cwd, config_path))
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
            logger.info(f"Loaded config from {config_path}")
            # Mapping from nested config keys to argparse destinations
            nested_to_dest = {
                ("voice", "name"): "voice",
                ("voice", "type"): "voice_type",
                ("audio", "sample_rate"): "sample_rate",
                ("audio", "noise_reduction"): "noise_reduction",
                ("audio", "echo_cancellation"): "echo_cancellation",
                ("turn_detection", "type"): "vad_type",
                ("turn_detection", "threshold"): "vad_threshold",
                ("turn_detection", "silence_duration_ms"): "silence_duration_ms",
                ("turn_detection", "use_eou_detection"): "use_eou_detection",
                ("turn_detection", "eou_model"): "eou_model",
                ("turn_detection", "enable_barge_in"): "enable_barge_in",
            }
            # Apply file values as defaults (CLI args take precedence)
            for key, val in file_config.items():
                if isinstance(val, dict):
                    for k2, v2 in val.items():
                        dest = nested_to_dest.get((key, k2), k2)
                        if hasattr(args, dest) and parser.get_default(dest) == getattr(args, dest):
                            setattr(args, dest, v2)
                elif hasattr(args, key) and parser.get_default(key) == getattr(args, key):
                    setattr(args, key, val)
        else:
            logger.warning(f"Config file not found: {config_path}")

    # Resolve paths relative to the ORIGINAL working directory (where user invoked)
    if not os.path.isabs(args.test_files_path):
        args.test_files_path = os.path.normpath(os.path.join(original_cwd, args.test_files_path))
    if not os.path.isabs(args.output_dir):
        args.output_dir = os.path.normpath(os.path.join(original_cwd, args.output_dir))
    if args.evaluation_dir and not os.path.isabs(args.evaluation_dir):
        args.evaluation_dir = os.path.normpath(os.path.join(original_cwd, args.evaluation_dir))
    if args.aggregate_eval_file and not os.path.isabs(args.aggregate_eval_file):
        args.aggregate_eval_file = os.path.normpath(os.path.join(original_cwd, args.aggregate_eval_file))

    # Now change to script directory — .env, logs, and defaults are relative to here
    os.chdir(script_dir)

    # Load env from script directory (.env lives next to the script)
    load_dotenv(os.path.join(script_dir, ".env"), override=True)

    # Logging — file handler + console
    log_level = logging.DEBUG if args.verbose else logging.INFO
    os.makedirs('logs', exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file_handler = logging.FileHandler(f'logs/{ts}_voicelive_eval.log', mode='w', encoding='utf-8')
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter('%(asctime)s:%(name)s:%(levelname)s:%(message)s'))
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter('%(asctime)s:%(name)s:%(levelname)s:%(message)s'))
    logging.basicConfig(level=log_level, format='%(asctime)s:%(name)s:%(levelname)s:%(message)s', handlers=[file_handler, console_handler])

    try:
        asyncio.run(main_async(args))
    finally:
        # Clean up Foundry temp download dir
        if _foundry_temp_dir and os.path.isdir(_foundry_temp_dir):
            shutil.rmtree(_foundry_temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
