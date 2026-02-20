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
    FunctionCallOutputItem,
    ItemType,
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
    
    def to_eval_format(self, ground_truth: str = "", tool_definitions: List[Dict] = None,
                       question: str = "") -> Dict[str, Any]:
        """Convert turn data to evaluation dataset format.
        
        Query source priority:
          1. Ground-truth question from input JSONL metadata (if present)
          2. VoiceLive real-time transcription (fallback)
        """
        ground_truth_query_used = bool(question)
        query_text = question if ground_truth_query_used else (self.user_transcription or "")
        return {
            "query": query_text,
            "response": self.assistant_response,
            "transcript": self.user_transcription or "",
            "ground_truth_query_used": ground_truth_query_used,
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
        
        # Build turn detection
        # VAD is always configured to ensure valid session. In PTT mode,
        # we additionally use commit() + response.create() for explicit
        # turn boundaries, but keep VAD as the base turn detection.
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
        
        # Send audio in small chunks with real-time pacing.
        # 20ms chunks at sample_rate, simulating real-time playback so VAD
        # can detect speech boundaries naturally.
        chunk_samples = int(sample_rate * 0.02)  # 20ms worth of samples
        chunk_bytes = chunk_samples * 2  # PCM16 = 2 bytes per sample
        
        # PTT vs VAD have fundamentally different send patterns:
        # - PTT: Send all audio → commit → response.create → THEN collect events
        #   (no events arrive until we explicitly request a response)
        # - VAD: Send audio concurrently with event collection, because VAD
        #   triggers responses during audio send based on speech boundaries
        
        if push_to_talk:
            # PTT: Sequential send → commit → response.create, THEN collect
            logger.info("PTT mode: sending audio synchronously before event collection")
            for i in range(0, len(audio_data), chunk_bytes):
                chunk = audio_data[i:i + chunk_bytes]
                encoded = base64.b64encode(chunk).decode('utf-8')
                await self._connection.input_audio_buffer.append(audio=encoded)
                await asyncio.sleep(0.02)  # Real-time pacing
            
            turn.audio_send_end_time = datetime.now()
            await self._connection.input_audio_buffer.commit()
            await self._connection.response.create()
            logger.debug("Audio committed and response.create sent (PTT)")
        
        # For VAD mode: concurrent audio send + event collection
        audio_send_complete = asyncio.Event()
        audio_task = None
        silence_task = None
        silence_chunk = base64.b64encode(b'\x00' * chunk_bytes).decode('utf-8')
        
        if not push_to_talk:
            async def send_audio():
                """Send audio chunks with real-time pacing (VAD mode)."""
                try:
                    for i in range(0, len(audio_data), chunk_bytes):
                        chunk = audio_data[i:i + chunk_bytes]
                        encoded = base64.b64encode(chunk).decode('utf-8')
                        await self._connection.input_audio_buffer.append(audio=encoded)
                        await asyncio.sleep(0.02)  # Real-time pacing
                    turn.audio_send_end_time = datetime.now()
                    logger.debug("Audio sent, starting silence keepalive for VAD")
                except Exception as e:
                    logger.error(f"Audio send error: {e}")
                finally:
                    audio_send_complete.set()
            
            async def send_silence():
                """Send silence chunks to keep audio buffer active for VAD."""
                try:
                    await audio_send_complete.wait()
                    while True:
                        await self._connection.input_audio_buffer.append(audio=silence_chunk)
                        await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.debug(f"Silence keepalive ended: {e}")
            
            audio_task = asyncio.create_task(send_audio())
            silence_task = asyncio.create_task(send_silence())
        
        # Event collection state
        response_done_received = False
        text_buffer = ""
        audio_transcript_buffer = ""
        tool_output_sent = False
        pending_tool_call = None  # SDK sample: execute tool AFTER response.done
        pending_tool_item_id = None  # previous_item_id for conversation.item.create
        
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
                    
                    # SDK sample: Detect function call items early to capture previous_item_id
                    elif event_type == ServerEventType.CONVERSATION_ITEM_CREATED:
                        if hasattr(event, 'item') and hasattr(event.item, 'type'):
                            if event.item.type == ItemType.FUNCTION_CALL:
                                pending_tool_item_id = event.item.id
                                logger.info(f"Function call item created: {event.item.name} (id={event.item.id})")
                    
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
                    
                    # Function call arguments done — store as pending
                    # SDK sample: Do NOT execute yet; wait for RESPONSE_DONE first
                    elif event_type == ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
                        if hasattr(event, 'call_id') and hasattr(event, 'arguments'):
                            tool_call = {
                                "call_id": event.call_id,
                                "name": getattr(event, 'name', 'unknown'),
                                "arguments": event.arguments
                            }
                            turn.tool_calls.append(tool_call)
                            logger.info(f"Tool call: {tool_call['name']}({event.arguments[:100]})")
                            pending_tool_call = event  # Store for execution after response.done
                    
                    # Response complete
                    elif event_type == ServerEventType.RESPONSE_DONE:
                        logger.debug("response.done received")
                        
                        # SDK sample: Execute pending tool call AFTER response.done
                        if pending_tool_call is not None:
                            logger.info("Executing pending tool call after response.done")
                            tool_output_sent = await self._execute_and_send_tool_result(
                                pending_tool_call, turn, pending_tool_item_id
                            )
                            pending_tool_call = None
                            pending_tool_item_id = None
                            if tool_output_sent:
                                # Wait for follow-up response
                                continue
                            # If send failed, finalize turn
                        
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
            # Cancel background tasks
            if silence_task and not silence_task.done():
                silence_task.cancel()
                try:
                    await silence_task
                except asyncio.CancelledError:
                    pass
            if audio_task and not audio_task.done():
                audio_task.cancel()
                try:
                    await audio_task
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
        Fix #3 + CR-1: After response.done, wait briefly for late-arriving
        transcript/text events before finalizing the turn.
        Handles both delta and done events.
        """
        # Mutable local buffers to accumulate late deltas
        late_audio_transcript = audio_transcript_buffer
        late_text = text_buffer
        
        try:
            async with asyncio.timeout(drain_seconds):
                async for event in self._connection:
                    event_type = event.type
                    
                    if event_type == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
                        turn.transcription_complete_time = datetime.now()
                        if hasattr(event, 'transcript') and event.transcript:
                            turn.user_transcription = event.transcript
                        logger.debug(f"Late transcription: {turn.user_transcription[:60]}")
                    
                    # CR-1: Also handle delta events during drain
                    elif event_type == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA:
                        if hasattr(event, 'delta') and event.delta:
                            late_audio_transcript += event.delta
                    
                    elif event_type == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
                        transcript = getattr(event, 'transcript', '') or late_audio_transcript
                        if transcript and len(transcript) > len(turn.assistant_response):
                            turn.assistant_response = transcript
                        late_audio_transcript = ""
                    
                    elif event_type == ServerEventType.RESPONSE_TEXT_DELTA:
                        if hasattr(event, 'delta') and event.delta:
                            late_text += event.delta
                    
                    elif event_type == ServerEventType.RESPONSE_TEXT_DONE:
                        text = getattr(event, 'text', '') or late_text
                        if text and len(text) > len(turn.assistant_response):
                            turn.assistant_response = text
                        late_text = ""
                    
                    elif event_type == ServerEventType.RESPONSE_DONE:
                        break
                    
                    elif event_type == ServerEventType.ERROR:
                        break
                    
        except asyncio.TimeoutError:
            # Use accumulated buffer content if no done event arrived
            if late_audio_transcript and len(late_audio_transcript) > len(turn.assistant_response):
                turn.assistant_response = late_audio_transcript
            elif late_text and len(late_text) > len(turn.assistant_response):
                turn.assistant_response = late_text
            logger.debug("Post-response drain completed (timeout)")
    
    async def _execute_and_send_tool_result(
        self,
        event,
        turn: ConversationTurn,
        previous_item_id: Optional[str] = None
    ) -> bool:
        """
        Execute a tool call locally and send the result back to VoiceLive
        using the SDK-pattern (FunctionCallOutputItem + previous_item_id).
        
        Returns True if tool output was successfully sent, False otherwise.
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
        
        # Send result back to VoiceLive using SDK-pattern typed model
        try:
            function_output = FunctionCallOutputItem(
                call_id=call_id,
                output=result_text
            )
            
            create_kwargs = {"item": function_output}
            if previous_item_id:
                create_kwargs["previous_item_id"] = previous_item_id
            
            await self._connection.conversation.item.create(**create_kwargs)
            logger.info(f"Tool result sent: {name} -> {result_text[:100]} (prev_item={previous_item_id})")
            
            # CR-2: Brief delay to let server register tool output
            await asyncio.sleep(0.05)
            
            # Request follow-up response incorporating tool output
            await self._connection.response.create()
            logger.debug("Requested follow-up response after tool result")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send tool result: {e}")
            return False
    
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
        
        # CR-3: Return explicit error for unknown tools so model can respond appropriately
        return json.dumps({"error": f"Unknown tool: {name}", "status": "not_found"})
