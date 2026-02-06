"""
VoiceLive Audio Processor - Configuration

Manages session configuration for VoiceLive connections.
Designed to be dynamically changeable and extensible for future agent modes.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum


class ProcessorMode(str, Enum):
    """Processing mode for VoiceLive connections."""
    AUDIO_EVALUATION = "audio_evaluation"  # Current mode: process audio for evaluation
    AGENT_MODE = "agent_mode"  # Future: interactive agent mode


class VadType(str, Enum):
    """Voice Activity Detection types."""
    SERVER_VAD = "server_vad"  # Volume-based (default)
    AZURE_SEMANTIC = "azure_semantic_vad_multilingual"  # Semantic meaning-based


class TranscriptionModel(str, Enum):
    """Supported transcription models."""
    GPT4O_TRANSCRIBE = "gpt-4o-transcribe"  # For gpt-realtime
    GPT4O_MINI_TRANSCRIBE = "gpt-4o-mini-transcribe"  # For gpt-realtime-mini
    AZURE_SPEECH = "azure-speech"  # For non-GPT models
    WHISPER = "whisper-1"  # Alternative


@dataclass
class VoiceConfig:
    """Voice configuration for TTS output."""
    name: str = "en-US-Ava:DragonHDLatestNeural"
    type: str = "azure-standard"


class EouModel(str, Enum):
    """End of Utterance detection models."""
    SEMANTIC_V1_MULTILINGUAL = "semantic_detection_v1_multilingual"
    # Add more models as they become available


@dataclass
class TurnDetectionConfig:
    """Turn detection (VAD) configuration."""
    type: VadType = VadType.AZURE_SEMANTIC
    threshold: Optional[float] = None  # SDK default
    prefix_padding_ms: Optional[int] = None
    silence_duration_ms: Optional[int] = None
    use_eou_detection: bool = True  # End-of-utterance detection (non-GPT models only)
    eou_model: EouModel = EouModel.SEMANTIC_V1_MULTILINGUAL  # EOU detection model


@dataclass
class AudioConfig:
    """Audio processing configuration."""
    sample_rate: int = 24000
    input_format: str = "pcm16"
    output_format: str = "pcm16"
    noise_reduction: str = "azure_deep_noise_suppression"
    echo_cancellation: str = "server_echo_cancellation"


@dataclass
class SessionConfig:
    """
    VoiceLive session configuration.
    
    This configuration is used to initialize VoiceLive connections.
    It can be customized per-job or set as defaults via environment.
    
    Designed for extensibility:
    - Current: Audio evaluation mode
    - Future: Agent mode with tool execution
    """
    # Core settings
    instructions: str = "You are a helpful agent assisting users with their questions."
    modalities: List[str] = field(default_factory=lambda: ["audio", "text"])
    
    # Voice and audio
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    turn_detection: TurnDetectionConfig = field(default_factory=TurnDetectionConfig)
    
    # Model-specific
    model: str = "gpt-realtime"  # Model determines transcription model
    transcription_model: Optional[str] = None  # Auto-set based on model if None
    
    # Tools (for future agent mode)
    tools: Optional[List[Dict[str, Any]]] = None
    tool_definitions: Optional[List[Dict[str, Any]]] = None
    
    # Processing mode
    mode: ProcessorMode = ProcessorMode.AUDIO_EVALUATION
    
    def get_transcription_model(self) -> str:
        """Get the appropriate transcription model based on main model."""
        if self.transcription_model:
            return self.transcription_model
        
        if self.model == "gpt-realtime":
            return TranscriptionModel.GPT4O_TRANSCRIBE.value
        elif self.model == "gpt-realtime-mini":
            return TranscriptionModel.GPT4O_MINI_TRANSCRIBE.value
        else:
            return TranscriptionModel.AZURE_SPEECH.value
    
    def supports_eou_detection(self) -> bool:
        """Check if the model supports end-of-utterance detection."""
        # GPT-realtime models do not support EOU detection
        return self.model not in ["gpt-realtime", "gpt-realtime-mini"]
    
    def get_final_instructions(self) -> str:
        """Get instructions with tool usage hint if tools are configured."""
        if self.tools:
            return f"{self.instructions} Use available tools when appropriate."
        return self.instructions
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "instructions": self.instructions[:100] + "..." if len(self.instructions) > 100 else self.instructions,
            "modalities": self.modalities,
            "voice": {"name": self.voice.name, "type": self.voice.type},
            "model": self.model,
            "transcription_model": self.get_transcription_model(),
            "turn_detection": {
                "type": self.turn_detection.type.value,
                "threshold": self.turn_detection.threshold,
                "silence_duration_ms": self.turn_detection.silence_duration_ms,
                "use_eou_detection": self.turn_detection.use_eou_detection and self.supports_eou_detection(),
                "eou_model": self.turn_detection.eou_model.value if self.turn_detection.use_eou_detection else None
            },
            "audio": {
                "sample_rate": self.audio.sample_rate,
                "noise_reduction": self.audio.noise_reduction,
                "echo_cancellation": self.audio.echo_cancellation
            },
            "tools_count": len(self.tools) if self.tools else 0,
            "mode": self.mode.value
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionConfig":
        """Create SessionConfig from dictionary."""
        config = cls()
        
        if "instructions" in data:
            config.instructions = data["instructions"]
        if "modalities" in data:
            config.modalities = data["modalities"]
        if "model" in data:
            config.model = data["model"]
        if "transcription_model" in data:
            config.transcription_model = data["transcription_model"]
        
        # Voice config
        if "voice" in data:
            voice_data = data["voice"]
            config.voice = VoiceConfig(
                name=voice_data.get("name", config.voice.name),
                type=voice_data.get("type", config.voice.type)
            )
        
        # Audio config
        if "audio" in data:
            audio_data = data["audio"]
            config.audio = AudioConfig(
                sample_rate=audio_data.get("sample_rate", config.audio.sample_rate),
                noise_reduction=audio_data.get("noise_reduction", config.audio.noise_reduction),
                echo_cancellation=audio_data.get("echo_cancellation", config.audio.echo_cancellation)
            )
        
        # Turn detection
        if "turn_detection" in data:
            td_data = data["turn_detection"]
            eou_model = EouModel.SEMANTIC_V1_MULTILINGUAL
            if "eou_model" in td_data and td_data["eou_model"]:
                try:
                    eou_model = EouModel(td_data["eou_model"])
                except ValueError:
                    pass  # Use default
            
            config.turn_detection = TurnDetectionConfig(
                type=VadType(td_data.get("type", VadType.AZURE_SEMANTIC.value)),
                threshold=td_data.get("threshold"),
                prefix_padding_ms=td_data.get("prefix_padding_ms"),
                silence_duration_ms=td_data.get("silence_duration_ms"),
                use_eou_detection=td_data.get("use_eou_detection", True),
                eou_model=eou_model
            )
        
        # Tools
        if "tools" in data:
            config.tools = data["tools"]
        if "tool_definitions" in data:
            config.tool_definitions = data["tool_definitions"]
        
        # Mode
        if "mode" in data:
            config.mode = ProcessorMode(data["mode"])
        
        return config


# Default configuration instance
DEFAULT_SESSION_CONFIG = SessionConfig()
