"""
VoiceLive Audio Processor - SDK Client

Native VoiceLive SDK client implementation without legacy wrappers.
Uses azure-ai-voicelive SDK directly with async/await pattern.
"""

import asyncio
import json
import logging
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
        logger.info(f"Connecting to VoiceLive: {self.endpoint}, model: {self.model}")
        self._connection = await voicelive_connect(
            endpoint=self.endpoint,
            credential=self.credential,
            model=self.model,
        ).__aenter__()
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
        
        # Build voice
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
        timeout_seconds: float = 60.0,
        push_to_talk: bool = False
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
            
        Returns:
            ConversationTurn with collected data
        """
        if not self._connection:
            raise RuntimeError("Not connected")
        
        turn = ConversationTurn()
        
        # Send audio in chunks
        import base64
        chunk_size = 4800  # 100ms at 24kHz
        
        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i:i + chunk_size]
            encoded = base64.b64encode(chunk).decode('utf-8')
            await self._connection.input_audio_buffer.append(audio=encoded)
        
        turn.audio_send_end_time = datetime.now()
        
        if push_to_talk:
            # Explicitly signal end of audio input (push-to-talk scenario)
            await self._connection.input_audio_buffer.commit()
            logger.debug("Audio sent and committed (push-to-talk)")
        else:
            # Let VAD detect end of speech naturally (default, real-world simulation)
            logger.debug("Audio sent, waiting for VAD end-of-speech detection")
        
        # Collect response events
        response_complete = False
        text_buffer = ""
        current_tool_call = None
        
        try:
            async with asyncio.timeout(timeout_seconds):
                async for event in self._connection:
                    event_type = event.type
                    
                    # Session created
                    if event_type == ServerEventType.SESSION_CREATED:
                        self._session_id = getattr(event.session, 'id', None)
                        logger.debug(f"Session: {self._session_id}")
                    
                    # Transcription completed
                    elif event_type == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
                        turn.transcription_complete_time = datetime.now()
                        if hasattr(event, 'transcript'):
                            turn.user_transcription = event.transcript or ""
                        logger.debug(f"Transcription: {turn.user_transcription[:50]}...")
                    
                    # Response text delta
                    elif event_type == ServerEventType.RESPONSE_TEXT_DELTA:
                        if turn.first_text_response_time is None:
                            turn.first_text_response_time = datetime.now()
                        if hasattr(event, 'delta') and event.delta:
                            text_buffer += event.delta
                    
                    # Response text done
                    elif event_type == ServerEventType.RESPONSE_TEXT_DONE:
                        if hasattr(event, 'text') and event.text:
                            turn.assistant_response = event.text
                        elif text_buffer:
                            turn.assistant_response = text_buffer
                    
                    # Audio transcript delta (for audio responses)
                    elif event_type == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA:
                        if turn.first_text_response_time is None:
                            turn.first_text_response_time = datetime.now()
                        if hasattr(event, 'delta') and event.delta:
                            text_buffer += event.delta
                    
                    # Audio transcript done
                    elif event_type == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
                        if hasattr(event, 'transcript') and event.transcript:
                            turn.assistant_response = event.transcript
                        elif text_buffer:
                            turn.assistant_response = text_buffer
                    
                    # Audio response
                    elif event_type == ServerEventType.RESPONSE_AUDIO_DELTA:
                        if turn.first_audio_response_time is None:
                            turn.first_audio_response_time = datetime.now()
                            turn.assistant_audio_received = True
                    
                    # Function call
                    elif event_type == ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
                        if hasattr(event, 'call_id') and hasattr(event, 'arguments'):
                            tool_call = {
                                "call_id": event.call_id,
                                "name": getattr(event, 'name', 'unknown'),
                                "arguments": event.arguments
                            }
                            turn.tool_calls.append(tool_call)
                            logger.debug(f"Tool call: {tool_call['name']}")
                    
                    # Response complete
                    elif event_type == ServerEventType.RESPONSE_DONE:
                        response_complete = True
                        logger.debug("Response complete")
                        break
                    
                    # Error
                    elif event_type == ServerEventType.ERROR:
                        error_msg = getattr(event, 'error', {})
                        logger.error(f"VoiceLive error: {error_msg}")
                        break
                        
        except asyncio.TimeoutError:
            logger.warning(f"Response timeout after {timeout_seconds}s")
        
        # Ensure we have some response text
        if not turn.assistant_response and text_buffer:
            turn.assistant_response = text_buffer
        
        return turn
    
    async def send_tool_result(self, call_id: str, result: str) -> None:
        """Send tool execution result back to VoiceLive (for future agent mode)."""
        if not self._connection:
            raise RuntimeError("Not connected")
        
        await self._connection.conversation.item.create(
            item={
                "type": "function_call_output",
                "call_id": call_id,
                "output": result
            }
        )
        logger.debug(f"Tool result sent for call_id: {call_id}")
