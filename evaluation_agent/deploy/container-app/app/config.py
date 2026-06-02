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
    enable_barge_in: bool = True  # Auto-truncation for interrupt handling


@dataclass
class AudioConfig:
    """Audio processing configuration."""
    sample_rate: int = 24000
    input_format: str = "pcm16"
    output_format: str = "pcm16"
    noise_reduction: str = "azure_deep_noise_suppression"
    echo_cancellation: str = "server_echo_cancellation"


@dataclass
class AgentConfig:
    """Foundry Agent configuration for agent mode."""
    agent_name: str = ""
    project_name: str = ""
    agent_version: Optional[str] = None
    conversation_id: Optional[str] = None
    foundry_resource_override: Optional[str] = None
    authentication_identity_client_id: Optional[str] = None


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
    
    # Audio input end detection
    # False = VAD detects end of speech automatically (server manages turns)
    # True  = Audio is committed + response.create() called explicitly,
    #         while VAD remains configured (VoiceLive requires turn_detection).
    push_to_talk: bool = False
    
    # Processing mode
    mode: ProcessorMode = ProcessorMode.AUDIO_EVALUATION
    
    # Agent mode (Foundry Agent integration)
    agent: Optional[AgentConfig] = None
    
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
    
    @property
    def is_agent_mode(self) -> bool:
        """True when agent config is set with name and project."""
        return self.agent is not None and bool(self.agent.agent_name and self.agent.project_name)

    def build_agent_config(self) -> Optional[Dict[str, Any]]:
        """Build agent connection kwargs for VoiceLive connect().

        azure-ai-voicelive 1.2.0 passes agent settings as individual connect()
        keyword arguments; the keys here match those kwarg names.
        """
        if not self.is_agent_mode or self.agent is None:
            return None
        config: Dict[str, Any] = {
            "agent_name": self.agent.agent_name,
            "project_name": self.agent.project_name,
        }
        if self.agent.agent_version:
            config["agent_version"] = self.agent.agent_version
        if self.agent.conversation_id:
            config["conversation_id"] = self.agent.conversation_id
        if self.agent.foundry_resource_override:
            config["foundry_resource_override"] = self.agent.foundry_resource_override
        if self.agent.authentication_identity_client_id and self.agent.foundry_resource_override:
            config["authentication_identity_client_id"] = self.agent.authentication_identity_client_id
        return config
    
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
            "mode": self.mode.value,
            "push_to_talk": self.push_to_talk,
            "enable_barge_in": self.turn_detection.enable_barge_in,
            "agent": {
                "agent_name": self.agent.agent_name,
                "project_name": self.agent.project_name,
                "agent_version": self.agent.agent_version,
            } if self.agent else None,
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
                eou_model=eou_model,
                enable_barge_in=bool(td_data.get("enable_barge_in", True))
            )
        
        # Agent config
        if "agent" in data:
            agent_data = data["agent"]
            config.agent = AgentConfig(
                agent_name=agent_data.get("agent_name", ""),
                project_name=agent_data.get("project_name", ""),
                agent_version=agent_data.get("agent_version"),
                conversation_id=agent_data.get("conversation_id"),
                foundry_resource_override=agent_data.get("foundry_resource_override"),
                authentication_identity_client_id=agent_data.get("authentication_identity_client_id"),
            )
            config.mode = ProcessorMode.AGENT_MODE
            # Validate: agent mode requires both agent_name and project_name
            if config.agent and (config.agent.agent_name or config.agent.project_name):
                if not config.agent.agent_name or not config.agent.project_name:
                    missing = "project_name" if config.agent.agent_name else "agent_name"
                    raise ValueError(
                        f"Incomplete agent config: {missing} is required when "
                        f"{'agent_name' if config.agent.agent_name else 'project_name'} is set"
                    )
        
        # Tools
        if "tools" in data:
            config.tools = data["tools"]
        if "tool_definitions" in data:
            config.tool_definitions = data["tool_definitions"]
        
        # Mode
        if "mode" in data:
            config.mode = ProcessorMode(data["mode"])
        
        # Push-to-talk
        if "push_to_talk" in data:
            config.push_to_talk = bool(data["push_to_talk"])
        
        return config


# Default configuration instance
DEFAULT_SESSION_CONFIG = SessionConfig()
