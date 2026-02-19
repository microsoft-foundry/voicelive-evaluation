"""
Voice Agent Audio Input Evaluation — Modern CLI Tool

Processes audio files through the Azure VoiceLive SDK for evaluation.
Uses async/await directly (no threading wrappers) with PTT/VAD mode support.
Patterns aligned with the container-app implementation.
"""

import os
import re
import json
import sys
import wave
import base64
import logging
import argparse
import asyncio
import numpy as np
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
    """Configuration for a VoiceLive session."""
    instructions: str = SYSTEM_INSTRUCTION
    model: str = "gpt-realtime"
    voice: str = "en-US-Ava:DragonHDLatestNeural"
    voice_type: str = "azure-standard"
    sample_rate: int = 24000
    push_to_talk: bool = False
    tools: Optional[List[Dict[str, Any]]] = None
    tool_definitions: Optional[List[Dict[str, Any]]] = None

    def get_transcription_model(self) -> str:
        """Return the appropriate transcription model for the configured model."""
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
    """Parsed entry from a JSONL dataset file."""
    audio_path: str
    ground_truth: Optional[str] = None
    question: Optional[str] = None
    tool_definitions: Optional[List[Dict[str, Any]]] = None
    conversation_id: str = "default"
    system_prompt: Optional[str] = None


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
    """Load a WAV file and return PCM16 bytes resampled to *target_rate*."""
    with wave.open(path, 'rb') as wf:
        sample_rate = wf.getframerate()
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())

    if sample_width == 2:
        audio = np.frombuffer(raw, dtype=np.int16)
    elif sample_width == 1:
        audio = np.frombuffer(raw, dtype=np.uint8).astype(np.int16) * 256
    else:
        raise ValueError(f"Unsupported sample width: {sample_width}")

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
    """Read a JSONL dataset file and return parsed entries."""
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

            wav_path = record.get('WavPath') or record.get('audio') or record.get('audio_path')
            if not wav_path:
                logger.warning(f"Line {line_num}: missing audio path field")
                continue

            # Resolve path
            resolved = _resolve_audio_path(wav_path, dataset_dir)
            if not resolved:
                logger.warning(f"Audio file not found: {wav_path}")
                continue

            tool_defs = record.get('tool_definitions', [])
            if isinstance(tool_defs, dict):
                tool_defs = [tool_defs]

            entries.append(DatasetEntry(
                audio_path=resolved,
                ground_truth=record.get('Answer') or record.get('answer'),
                question=record.get('Question') or record.get('question'),
                tool_definitions=tool_defs if tool_defs else [],
                conversation_id=record.get('conversationID') or record.get('conversation_id') or 'default',
                system_prompt=record.get('system_prompt'),
            ))

    logger.info(f"Loaded {len(entries)} entries from {path}")
    return entries


def _resolve_audio_path(wav_path: str, dataset_dir: str) -> Optional[str]:
    """Try several strategies to locate an audio file."""
    if os.path.isabs(wav_path) and os.path.exists(wav_path):
        return wav_path
    # Relative to dataset dir (basename)
    candidate = os.path.join(dataset_dir, os.path.basename(wav_path))
    if os.path.exists(candidate):
        return os.path.abspath(candidate)
    # Full relative from dataset dir
    candidate = os.path.join(dataset_dir, wav_path)
    if os.path.exists(candidate):
        return os.path.abspath(candidate)
    # Walk up to 5 parent directories
    current = dataset_dir
    for _ in range(5):
        candidate = os.path.join(current, wav_path)
        if os.path.exists(candidate):
            return os.path.abspath(candidate)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
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

    # Turn detection — always configured (VoiceLive requires it, even for PTT)
    if config.supports_eou_detection():
        sdk_turn_detection = AzureSemanticVadMultilingual(
            end_of_utterance_detection=EouDetection(model="semantic_detection_v1_multilingual"),
        )
    else:
        sdk_turn_detection = AzureSemanticVadMultilingual()

    sdk_session = RequestSession(
        modalities=[Modality.TEXT, Modality.AUDIO],
        instructions=config.get_final_instructions(),
        voice=sdk_voice,
        turn_detection=sdk_turn_detection,
        input_audio_transcription=AudioInputTranscriptionOptions(model=config.get_transcription_model()),
        input_audio_noise_reduction=AudioNoiseReduction(type="azure_deep_noise_suppression"),
        input_audio_echo_cancellation=AudioEchoCancellation(type="server_echo_cancellation"),
        tools=config.tools if config.tools else None,
        input_audio_format=InputAudioFormat.PCM16,
        output_audio_format=OutputAudioFormat.PCM16,
        input_audio_sampling_rate=config.sample_rate,
    )
    await connection.session.update(session=sdk_session)
    logger.info(f"Session configured: model={config.model}, voice={config.voice}, ptt={config.push_to_talk}")


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
                            turn.response_audio_chunks.append(base64.b64decode(event.delta))
                        except Exception:
                            pass  # Skip malformed audio chunks

                elif etype == ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
                    if hasattr(event, 'call_id') and hasattr(event, 'arguments'):
                        tc = {
                            "call_id": event.call_id,
                            "name": getattr(event, 'name', 'unknown'),
                            "arguments": event.arguments,
                        }
                        turn.tool_calls.append(tc)
                        logger.info(f"Tool call: {tc['name']}({event.arguments[:100]})")
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
    drain_seconds: float = 2.0,
) -> None:
    """Wait briefly for late-arriving transcript events after response.done."""
    late_audio = audio_transcript_buffer
    late_text = text_buffer
    try:
        async with asyncio.timeout(drain_seconds):
            async for event in connection:
                etype = event.type
                if etype == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
                    turn.transcription_complete_time = datetime.now()
                    if hasattr(event, 'transcript') and event.transcript:
                        turn.user_transcription = event.transcript
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
    """
    query_messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_instructions}
    ]

    # Prior turns (chronological)
    for hist in conversation_history:
        for msg in hist.get("messages", []):
            query_messages.append(msg)

    # Current turn — user input
    user_text = sanitize_text_for_utf8(turn.user_transcription)
    if user_text:
        query_messages.append({"role": "user", "content": [{"type": "text", "text": user_text}]})

    # Current turn — tool messages
    for tr in turn.tool_results:
        query_messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": tr["call_id"], "type": "function",
                            "function": {"name": tr["name"], "arguments": json.dumps(tr.get("arguments", tr.get("args", {})))}}],
        })
        query_messages.append({
            "role": "tool",
            "tool_call_id": tr["call_id"],
            "content": tr["result"],
        })

    # Build response list
    response_messages: List[Dict[str, Any]] = []
    resp_text = sanitize_text_for_utf8(turn.assistant_response)
    if resp_text:
        response_messages.append({
            "role": "assistant",
            "content": resp_text,
        })

    metrics = turn.calculate_metrics()
    metrics["logical_turn_number"] = turn.turn_number
    metrics["audio_response_received"] = turn.assistant_audio_received

    return {
        "query": query_messages,
        "response": response_messages,
        "metrics": metrics,
        "tool_calls": turn.tool_calls or [],
        "tool_definitions": tool_definitions or [],
        "ground_truth": entry.ground_truth or "",
        "conversation_id": entry.conversation_id,
        "source_file": entry.audio_path,
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
        conv_config = SessionConfig(
            instructions=entries[0].system_prompt,
            model=config.model,
            voice=config.voice,
            voice_type=config.voice_type,
            sample_rate=config.sample_rate,
            push_to_talk=config.push_to_talk,
            tools=config.tools,
            tool_definitions=config.tool_definitions,
        )
    if entries and entries[0].tool_definitions:
        tool_defs = entries[0].tool_definitions
        if isinstance(tool_defs, dict):
            tool_defs = [tool_defs]
        conv_config = SessionConfig(
            instructions=conv_config.instructions,
            model=conv_config.model,
            voice=conv_config.voice,
            voice_type=conv_config.voice_type,
            sample_rate=conv_config.sample_rate,
            push_to_talk=conv_config.push_to_talk,
            tools=tool_defs,
            tool_definitions=tool_defs,
        )

    await configure_session(connection, conv_config)

    effective_tool_defs = conv_config.tool_definitions or []

    for i, entry in enumerate(entries):
        turn_number = i + 1
        try:
            audio_data = load_audio_file(entry.audio_path, conv_config.sample_rate)
            logger.info(f"Loaded {entry.audio_path} ({len(audio_data)} bytes)")

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
                audio_out_dir = os.path.join(output_dir, entry.conversation_id)
                save_response_audio(turn, audio_out_dir, entry.conversation_id, conv_config.sample_rate)

            # Update conversation history for subsequent turns
            turn_messages: List[Dict[str, Any]] = []
            user_text = sanitize_text_for_utf8(turn.user_transcription)
            if user_text:
                turn_messages.append({"role": "user", "content": [{"type": "text", "text": user_text}]})
            # Include assistant tool_calls announcement (so evaluators see the full chain)
            if turn.tool_results:
                turn_messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": tr["call_id"], "type": "function",
                         "function": {"name": tr["name"],
                                      "arguments": json.dumps(tr.get("arguments", tr.get("args", {})))}}
                        for tr in turn.tool_results
                    ],
                })
            resp_text = sanitize_text_for_utf8(turn.assistant_response)
            if resp_text:
                turn_messages.append({"role": "assistant", "content": resp_text})
            for tr in turn.tool_results:
                turn_messages.append({"role": "tool", "tool_call_id": tr["call_id"], "content": tr["result"]})
            conversation_history.append({"turn": turn_number, "messages": turn_messages})

            logger.info(f"Turn {turn_number} done: {os.path.basename(entry.audio_path)}")

        except Exception as e:
            logger.error(f"Error processing {entry.audio_path}: {e}")
            results.append({
                "conversation_id": entry.conversation_id,
                "source_file": entry.audio_path,
                "error": str(e),
                "turn_number": turn_number,
            })

    return results


def _append_jsonl(path: str, record: Dict[str, Any]) -> None:
    """Append a single JSON record to a JSONL file (thread-safe via append mode)."""
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
    model = (
        os.environ.get("AZURE_VOICELIVE_MODEL")
        or os.environ.get("AZURE_VOICE_LIVE_MODEL")
        or args.model
    )
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
        sample_rate=args.sample_rate,
        push_to_talk=args.push_to_talk,
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
    if not skip_eval and not aggregate_eval_file and eval_output_file:
        _run_evaluation(eval_output_file, args.output_dir,
                        eval_object_id=getattr(args, "eval_object_id", None))

    logger.info(f"Done — {len(all_results)} results written to {out_path}")


def _run_evaluation(
    eval_input_path: str,
    output_dir: str,
    eval_object_id: Optional[str] = None,
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
        eval_desc = f"Voice Live API: {ts}"
        eval_output = os.path.join(output_dir, ts)
        os.makedirs(eval_output, exist_ok=True)
        logger.info(f"Starting evaluation: {eval_name}")
        voice_agent_evaluation.main(
            eval_input_path,
            referenceTranscriptFilePath="",
            output_folder=eval_output,
            eval_group_name=eval_desc,
            eval_object_id=eval_object_id or "",
            eval_run_name=eval_name,
            eval_run_scenario=eval_name,
            dataset_id="",
            dataset_appendix="",
            setupCustomEvaluators=False,
        )
        logger.info(f"Evaluation completed (results in {eval_output})")
    except Exception as e:
        logger.error(f"Evaluation failed: {e}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse arguments and run."""
    # Change to script directory before anything else (ensures .env loading works)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    parser = argparse.ArgumentParser(
        description="Process audio files through the Azure VoiceLive SDK for evaluation"
    )
    parser.add_argument(
        '--test-files', '-f', dest='test_files_path', required=True,
        help='JSONL file listing audio files and metadata',
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
        '--model', default='gpt-realtime',
        help='VoiceLive model (default: gpt-realtime)',
    )
    parser.add_argument(
        '--voice', default='en-US-Ava:DragonHDLatestNeural',
        help='Voice name (default: en-US-Ava:DragonHDLatestNeural)',
    )
    parser.add_argument(
        '--sample-rate', dest='sample_rate', type=int, default=24000,
        help='Audio sample rate in Hz (default: 24000)',
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Enable DEBUG logging',
    )
    args = parser.parse_args()

    # Resolve paths relative to the (now current) script directory
    if not os.path.isabs(args.test_files_path):
        args.test_files_path = os.path.abspath(args.test_files_path)
    if not os.path.isabs(args.output_dir):
        args.output_dir = os.path.abspath(args.output_dir)
    if args.evaluation_dir and not os.path.isabs(args.evaluation_dir):
        args.evaluation_dir = os.path.abspath(args.evaluation_dir)
    if args.aggregate_eval_file and not os.path.isabs(args.aggregate_eval_file):
        args.aggregate_eval_file = os.path.abspath(args.aggregate_eval_file)

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

    # Load env — explicit path to .env in the script directory
    load_dotenv("./.env", override=True)

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
