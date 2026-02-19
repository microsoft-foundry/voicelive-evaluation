"""
VoiceLive Audio Processor - SDK Client

Native VoiceLive SDK client implementation without legacy wrappers.
Uses azure-ai-voicelive SDK directly with async/await pattern.
"""

import asyncio
import json
import logging
import os
import base64
from datetime import datetime
from typing import Optional, List, Dict, Any, AsyncIterator
from dataclasses import dataclass, field

from azure.identity import DefaultAzureCredential
from azure.core.credentials import TokenCredential
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
)

from .config import SessionConfig, VadType, EouModel

logger = logging.getLogger(__name__)


@dataclass
class ConversationTurn:
    """Data collected from a single conversation turn."""
    turn_number: int = 0
    user_transcription: str = ""
    assistant_response: str = ""
    assistant_audio_received: bool = False
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    
    # Timing metrics
    audio_send_end_time: Optional[datetime] = None
    transcription_complete_time: Optional[datetime] = None
    first_text_response_time: Optional[datetime] = None
    first_audio_response_time: Optional[datetime] = None
    
    def calculate_metrics(self) -> Dict[str, float]:
        """Calculate latency metrics for this turn."""
        metrics = {}
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
    
    def to_eval_format(self, ground_truth: str = "", tool_definitions: List[Dict] = None) -> Dict[str, Any]:
        """Convert turn data to evaluation dataset format."""
        return {
            "query": self.user_transcription,
            "response": self.assistant_response,
            "tool_calls": self.tool_calls if self.tool_calls else [],
            "tool_definitions": tool_definitions or [],
            "ground_truth": ground_truth,
            "metrics": self.calculate_metrics(),
            "audio_response_received": self.assistant_audio_received,
            "turn_number": self.turn_number
        }


class VoiceLiveClient:
    """
    Native VoiceLive SDK client.
    
    Uses async context manager pattern for clean connection lifecycle.
    Processes audio files and collects response data for evaluation.
    """
    
    def __init__(
        self,
        endpoint: str,
        model: str,
        credential: Optional[TokenCredential] = None
    ):
        self.endpoint = endpoint
        self.model = model
        self.credential = credential or DefaultAzureCredential()
        self._connection = None
        self._session_id: Optional[str] = None
        
    async def __aenter__(self):
        """Establish connection."""
        connect_kwargs = {
            "endpoint": self.endpoint,
            "credential": self.credential,
            "model": self.model,
        }
        # Use explicit api_version if set via environment variable
        api_version = os.environ.get("AZURE_VOICELIVE_API_VERSION")
        if api_version:
            connect_kwargs["api_version"] = api_version
        
        logger.info(f"Connecting to VoiceLive: {self.endpoint}, model: {self.model}, api_version: {api_version or 'SDK default'}")
        self._connection = await voicelive_connect(**connect_kwargs).__aenter__()
        logger.info("VoiceLive connection established")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close connection."""
        if self._connection:
            try:
                await self._connection.__aexit__(exc_type, exc_val, exc_tb)
                logger.info("VoiceLive connection closed")
            except Exception as e:
                logger.warning(f"Error closing connection: {e}")
        return False
    
    async def configure_session(self, config: SessionConfig) -> None:
        """
        Configure the VoiceLive session with SDK-native objects.
        
        Args:
            config: SessionConfig with all session parameters
        """
        if not self._connection:
            raise RuntimeError("Not connected")
        
        # Build modalities
        sdk_modalities = [
            Modality.AUDIO if m == "audio" else Modality.TEXT
            for m in config.modalities
        ]
        
        # Build voice - use OpenAIVoice for preset voices, AzureStandardVoice for Azure voices
        if config.voice.type == "preset":
            sdk_voice = OpenAIVoice(name=config.voice.name)
        else:
            sdk_voice = AzureStandardVoice(
                name=config.voice.name,
                type=config.voice.type
            )
        
        # Build transcription
        sdk_transcription = AudioInputTranscriptionOptions(
            model=config.get_transcription_model()
        )
        
        # Build turn detection (VAD)
        if config.turn_detection.type == VadType.AZURE_SEMANTIC:
            if config.supports_eou_detection() and config.turn_detection.use_eou_detection:
                sdk_turn_detection = AzureSemanticVadMultilingual(
                    threshold=config.turn_detection.threshold,
                    prefix_padding_ms=config.turn_detection.prefix_padding_ms,
                    silence_duration_ms=config.turn_detection.silence_duration_ms,
                    end_of_utterance_detection=EouDetection(model=config.turn_detection.eou_model.value)
                )
            else:
                sdk_turn_detection = AzureSemanticVadMultilingual(
                    threshold=config.turn_detection.threshold,
                    prefix_padding_ms=config.turn_detection.prefix_padding_ms,
                    silence_duration_ms=config.turn_detection.silence_duration_ms,
                )
        else:
            sdk_turn_detection = ServerVad(
                threshold=config.turn_detection.threshold,
                prefix_padding_ms=config.turn_detection.prefix_padding_ms,
                silence_duration_ms=config.turn_detection.silence_duration_ms,
            )
        
        # Build noise reduction and echo cancellation
        sdk_noise_reduction = AudioNoiseReduction(type=config.audio.noise_reduction)
        sdk_echo_cancellation = AudioEchoCancellation(type=config.audio.echo_cancellation)
        
        # Build SDK session request
        sdk_session = RequestSession(
            modalities=sdk_modalities,
            instructions=config.get_final_instructions(),
            voice=sdk_voice,
            turn_detection=sdk_turn_detection,
            input_audio_transcription=sdk_transcription,
            input_audio_noise_reduction=sdk_noise_reduction,
            input_audio_echo_cancellation=sdk_echo_cancellation,
            tools=config.tools,
            input_audio_format=InputAudioFormat.PCM16,
            output_audio_format=OutputAudioFormat.PCM16,
            input_audio_sampling_rate=config.audio.sample_rate,
        )
        
        # Send session update
        await self._connection.session.update(session=sdk_session)
        logger.info(f"Session configured: {config.to_dict()}")
    
    async def process_audio(
        self,
        audio_data: bytes,
        ground_truth: str = "",
        tool_definitions: List[Dict] = None,
        timeout_seconds: float = 120.0,
        push_to_talk: bool = False,
        sample_rate: int = 24000
    ) -> ConversationTurn:
        """
        Send audio and collect the response.
        
        Args:
            audio_data: PCM16 audio bytes
            ground_truth: Expected answer for evaluation
            tool_definitions: Tool definitions for evaluation dataset
            timeout_seconds: Max time to wait for response
            push_to_talk: If True, send explicit audio commit after all audio is sent.
                          If False (default), rely on VAD to detect end of speech.
            sample_rate: Audio sample rate for chunk pacing (default 24kHz)
            
        Returns:
            ConversationTurn with collected data
        """
        if not self._connection:
            raise RuntimeError("Not connected")
        
        turn = ConversationTurn()
        
        # Fix #1: Send audio in small chunks with real-time pacing
        # 20ms chunks at sample_rate, simulating real-time playback so VAD
        # can detect speech boundaries naturally.
        chunk_samples = int(sample_rate * 0.02)  # 20ms worth of samples
        chunk_bytes = chunk_samples * 2  # PCM16 = 2 bytes per sample
        
        for i in range(0, len(audio_data), chunk_bytes):
            chunk = audio_data[i:i + chunk_bytes]
            encoded = base64.b64encode(chunk).decode('utf-8')
            await self._connection.input_audio_buffer.append(audio=encoded)
            await asyncio.sleep(0.02)  # Real-time pacing: 20ms per 20ms chunk
        
        turn.audio_send_end_time = datetime.now()
        
        if push_to_talk:
            # Explicitly signal end of audio input
            await self._connection.input_audio_buffer.commit()
            logger.debug("Audio sent and committed (push-to-talk)")
        else:
            # Fix #2: Send silence keepalive while waiting for VAD to detect
            # end of speech. Without this, VAD may not trigger speech_stopped.
            logger.debug("Audio sent, sending silence keepalive for VAD detection")
        
        # Collect response events
        response_done_received = False
        text_buffer = ""
        audio_transcript_buffer = ""
        current_tool_call = None
        tool_output_sent = False
        
        # Fix #2: Silence keepalive task for VAD mode
        silence_task = None
        if not push_to_talk:
            silence_chunk = base64.b64encode(b'\x00' * chunk_bytes).decode('utf-8')
            
            async def send_silence():
                """Send silence chunks to keep audio buffer active for VAD."""
                try:
                    while True:
                        await self._connection.input_audio_buffer.append(audio=silence_chunk)
                        await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.debug(f"Silence keepalive ended: {e}")
            
            silence_task = asyncio.create_task(send_silence())
        
        try:
            async with asyncio.timeout(timeout_seconds):
                logger.info(f"Starting event collection (timeout={timeout_seconds}s, push_to_talk={push_to_talk})")
                async for event in self._connection:
                    event_type = event.type
                    
                    # Session created
                    if event_type == ServerEventType.SESSION_CREATED:
                        self._session_id = getattr(event.session, 'id', None)
                        logger.debug(f"Session: {self._session_id}")
                    
                    # Fix #5: Speech started — finalize pending turn state
                    elif event_type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
                        logger.debug("Speech started detected by VAD")
                    
                    # Fix #5: Speech stopped — record VAD end-of-speech time
                    elif event_type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
                        turn.audio_send_end_time = datetime.now()
                        logger.debug("Speech stopped detected by VAD")
                        # Stop silence keepalive once VAD detects end of speech
                        if silence_task and not silence_task.done():
                            silence_task.cancel()
                            silence_task = None
                    
                    # Transcription completed (user's speech → text)
                    elif event_type == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
                        turn.transcription_complete_time = datetime.now()
                        if hasattr(event, 'transcript'):
                            turn.user_transcription = event.transcript or ""
                        logger.debug(f"Transcription: {turn.user_transcription[:80]}...")
                    
                    # Response text delta (text modality)
                    elif event_type == ServerEventType.RESPONSE_TEXT_DELTA:
                        if turn.first_text_response_time is None:
                            turn.first_text_response_time = datetime.now()
                        if hasattr(event, 'delta') and event.delta:
                            text_buffer += event.delta
                    
                    # Response text done (text modality)
                    elif event_type == ServerEventType.RESPONSE_TEXT_DONE:
                        if hasattr(event, 'text') and event.text:
                            # Fix #12 + #6: Use text output if it's longer than current response
                            if len(event.text) > len(turn.assistant_response):
                                turn.assistant_response = event.text
                            elif not turn.assistant_response:
                                turn.assistant_response = event.text
                        elif text_buffer:
                            if len(text_buffer) > len(turn.assistant_response):
                                turn.assistant_response = text_buffer
                            elif not turn.assistant_response:
                                turn.assistant_response = text_buffer
                        text_buffer = ""
                    
                    # Audio transcript delta (for audio responses)
                    elif event_type == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA:
                        if turn.first_text_response_time is None:
                            turn.first_text_response_time = datetime.now()
                        if hasattr(event, 'delta') and event.delta:
                            audio_transcript_buffer += event.delta
                    
                    # Audio transcript done
                    elif event_type == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
                        transcript = ""
                        if hasattr(event, 'transcript') and event.transcript:
                            transcript = event.transcript
                        elif audio_transcript_buffer:
                            transcript = audio_transcript_buffer
                        # Fix #6: Don't overwrite a real response with a shorter one
                        # (handles multi-part "let me check..." + actual answer)
                        if transcript and len(transcript) > len(turn.assistant_response):
                            turn.assistant_response = transcript
                        elif transcript and not turn.assistant_response:
                            turn.assistant_response = transcript
                        audio_transcript_buffer = ""
                    
                    # Audio response
                    elif event_type == ServerEventType.RESPONSE_AUDIO_DELTA:
                        if turn.first_audio_response_time is None:
                            turn.first_audio_response_time = datetime.now()
                            turn.assistant_audio_received = True
                    
                    # Function call arguments done
                    elif event_type == ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
                        if hasattr(event, 'call_id') and hasattr(event, 'arguments'):
                            tool_call = {
                                "call_id": event.call_id,
                                "name": getattr(event, 'name', 'unknown'),
                                "arguments": event.arguments
                            }
                            turn.tool_calls.append(tool_call)
                            logger.info(f"Tool call: {tool_call['name']}({event.arguments[:100]})")
                            
                            # Fix #7: Execute tool and send result back
                            await self._execute_and_send_tool_result(event, turn)
                            tool_output_sent = True
                    
                    # Fix #3: Response complete — DON'T break immediately.
                    # Wait for late-arriving transcript events.
                    elif event_type == ServerEventType.RESPONSE_DONE:
                        logger.debug("response.done received")
                        
                        # If tool output was just sent, the model will produce a
                        # follow-up response. Don't finalize yet.
                        if tool_output_sent:
                            logger.info("Tool output sent, waiting for follow-up response")
                            tool_output_sent = False
                            continue
                        
                        response_done_received = True
                        # Stop silence keepalive
                        if silence_task and not silence_task.done():
                            silence_task.cancel()
                            silence_task = None
                        
                        # Drain: wait briefly for late transcript events
                        await self._drain_late_events(turn, audio_transcript_buffer, text_buffer)
                        break
                    
                    # Error
                    elif event_type == ServerEventType.ERROR:
                        error_msg = getattr(event, 'error', {})
                        logger.error(f"VoiceLive error: {error_msg}")
                        break
                    
                    # Log unhandled events for debugging
                    else:
                        logger.debug(f"VoiceLive event: {event_type}")
                        
        except asyncio.TimeoutError:
            logger.warning(f"Response timeout after {timeout_seconds}s")
        finally:
            # Always cancel silence keepalive
            if silence_task and not silence_task.done():
                silence_task.cancel()
                try:
                    await silence_task
                except asyncio.CancelledError:
                    pass
        
        # Final fallback: use any remaining buffer content
        if not turn.assistant_response:
            if audio_transcript_buffer:
                turn.assistant_response = audio_transcript_buffer
            elif text_buffer:
                turn.assistant_response = text_buffer
        
        logger.info(
            f"Turn complete: response_done={response_done_received}, "
            f"query='{turn.user_transcription[:60]}', "
            f"response='{turn.assistant_response[:60]}', "
            f"tool_calls={len(turn.tool_calls)}"
        )
        
        return turn
    
    async def _drain_late_events(
        self,
        turn: ConversationTurn,
        audio_transcript_buffer: str,
        text_buffer: str,
        drain_seconds: float = 2.0
    ) -> None:
        """
        Fix #3: After response.done, wait briefly for late-arriving
        transcript/text events before finalizing the turn.
        """
        try:
            async with asyncio.timeout(drain_seconds):
                async for event in self._connection:
                    event_type = event.type
                    
                    if event_type == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
                        turn.transcription_complete_time = datetime.now()
                        if hasattr(event, 'transcript') and event.transcript:
                            turn.user_transcription = event.transcript
                        logger.debug(f"Late transcription: {turn.user_transcription[:60]}")
                    
                    elif event_type == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
                        transcript = getattr(event, 'transcript', '') or audio_transcript_buffer
                        if transcript and len(transcript) > len(turn.assistant_response):
                            turn.assistant_response = transcript
                    
                    elif event_type == ServerEventType.RESPONSE_TEXT_DONE:
                        text = getattr(event, 'text', '') or text_buffer
                        if text and len(text) > len(turn.assistant_response):
                            turn.assistant_response = text
                    
                    elif event_type == ServerEventType.RESPONSE_DONE:
                        # Another response.done (e.g., from tool follow-up)
                        break
                    
                    elif event_type == ServerEventType.ERROR:
                        break
                    
        except asyncio.TimeoutError:
            logger.debug("Post-response drain completed (timeout)")
    
    async def _execute_and_send_tool_result(
        self,
        event,
        turn: ConversationTurn
    ) -> None:
        """
        Fix #7: Execute a tool call locally and send the result back to
        VoiceLive so the model can produce a tool-informed response.
        """
        call_id = event.call_id
        name = getattr(event, 'name', 'unknown')
        args_str = event.arguments or ""
        
        try:
            args = json.loads(args_str) if args_str else {}
        except (json.JSONDecodeError, TypeError):
            args = {"raw": args_str}
        
        # Execute tool (simple built-in tools or return placeholder)
        result_text = self._execute_tool(name, args)
        
        # Record tool result
        turn.tool_results.append({
            "call_id": call_id,
            "name": name,
            "result": result_text
        })
        
        # Send result back to VoiceLive
        try:
            await self._connection.conversation.item.create(
                item={
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": result_text
                }
            )
            logger.info(f"Tool result sent: {name} -> {result_text[:100]}")
            
            # Request follow-up response incorporating tool output
            await self._connection.response.create()
            logger.debug("Requested follow-up response after tool result")
            
        except Exception as e:
            logger.error(f"Failed to send tool result: {e}")
    
    def _execute_tool(self, name: str, args: dict) -> str:
        """Execute a tool by name. Override for custom tool registries."""
        # Built-in tool stubs for common evaluation scenarios
        TOOL_STUBS = {
            "get_weather": lambda **a: json.dumps({"temperature": 72, "condition": "sunny", "location": a.get("location", "unknown")}),
            "search": lambda **a: json.dumps({"results": [f"Result for: {a.get('query', '')}"]}),
            "get_time": lambda **a: json.dumps({"time": datetime.now().strftime("%H:%M"), "timezone": a.get("timezone", "UTC")}),
        }
        
        tool_fn = TOOL_STUBS.get(name)
        if tool_fn:
            try:
                return tool_fn(**args) if isinstance(args, dict) and "raw" not in args else f"[{name}: {args}]"
            except Exception as e:
                return f"[Tool {name} error: {e}]"
        
        return f"[Tool {name} executed successfully]"
