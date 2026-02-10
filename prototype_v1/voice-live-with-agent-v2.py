from __future__ import annotations

import argparse
import asyncio
import base64
import logging
import os
import pathlib
import queue
import signal
import sys
from datetime import datetime
from typing import Optional, Union, cast

import pyaudio
# from azure.ai.voicelive._types import InterimResponseConfig
from azure.ai.voicelive.aio import VoiceLiveConnection, connect
from azure.ai.voicelive.models import (AudioEchoCancellation,
                                       AudioNoiseReduction, AzureStandardVoice,
                                       InputAudioFormat,
                                       Modality,
                                       OutputAudioFormat, RequestSession,
                                       ServerEventType, ServerVad)
from azure.core.credentials import AzureKeyCredential
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import AzureCliCredential, DefaultAzureCredential
from dotenv import load_dotenv

# Change to the directory where this script is located
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Environment variable loading
load_dotenv('./.env', override=True)

# Set up logging
# Add folder for logging
pathlib.Path('logs').mkdir(exist_ok=True)

# Add timestamp for logfiles
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# Create conversation log filename
logfilename = f"{timestamp}_conversation.log"

# Set up logging
logging.basicConfig(
    filename=f'logs/{timestamp}_voicelive.log',
    filemode="w",
    format='%(asctime)s:%(name)s:%(levelname)s:%(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class AudioProcessor:
    """
    Handles real-time audio capture and playback for the voice assistant.

    Threading Architecture:
    - Main thread: Event loop and UI
    - Capture thread: PyAudio input stream reading
    - Send thread: Async audio data transmission to VoiceLive
    - Playback thread: PyAudio output stream writing
    """

    loop: asyncio.AbstractEventLoop


    class AudioPlaybackPacket:
        """Represents a packet that can be sent to the audio playback queue."""
        def __init__(self, seq_num: int, data: Optional[bytes]):
            self.seq_num = seq_num
            self.data = data

    def __init__(self, connection: VoiceLiveConnection):
        self.connection = connection
        self.audio = pyaudio.PyAudio()

        # Audio configuration - PCM16, 24kHz, mono as specified
        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 24000
        self.chunk_size = 1200  # 50ms

        # Capture and playback state
        self.input_stream: Optional[pyaudio.Stream] = None

        self.playback_queue: queue.Queue[AudioProcessor.AudioPlaybackPacket] = queue.Queue()
        self.playback_base = 0
        self.next_seq_num = 0
        self.output_stream: Optional[pyaudio.Stream] = None

        logger.info("AudioProcessor initialized with 24kHz PCM16 mono audio")

    def start_capture(self):
        """Start capturing audio from microphone."""
        def _capture_callback(
            in_data,      # data
            _frame_count,  # number of frames
            _time_info,    # dictionary
            _status_flags):
            """Audio capture thread - runs in background."""
            audio_base64 = base64.b64encode(in_data).decode("utf-8")
            asyncio.run_coroutine_threadsafe(
                self.connection.input_audio_buffer.append(audio=audio_base64), self.loop
            )
            return (None, pyaudio.paContinue)

        if self.input_stream:
            return

        # Store the current event loop for use in threads
        self.loop = asyncio.get_event_loop()

        try:
            self.input_stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk_size,
                stream_callback=_capture_callback,
            )
            logger.info("Started audio capture")

        except Exception:
            logger.exception("Failed to start audio capture")
            raise

    def start_playback(self):
        """Initialize audio playback system."""
        if self.output_stream:
            return

        remaining = bytes()
        def _playback_callback(
            _in_data,
            frame_count,  # number of frames
            _time_info,
            _status_flags):

            nonlocal remaining
            frame_count *= pyaudio.get_sample_size(pyaudio.paInt16)

            out = remaining[:frame_count]
            remaining = remaining[frame_count:]

            while len(out) < frame_count:
                try:
                    packet = self.playback_queue.get_nowait()
                except queue.Empty:
                    out = out + bytes(frame_count - len(out))
                    continue
                except Exception:
                    logger.exception("Error in audio playback")
                    raise

                if not packet or not packet.data:
                    # None packet indicates end of stream
                    logger.info("End of playback queue.")
                    break

                if packet.seq_num < self.playback_base:
                    # skip requested
                    # ignore skipped packet and clear remaining
                    if len(remaining) > 0:
                        remaining = bytes()
                    continue

                num_to_take = frame_count - len(out)
                out = out + packet.data[:num_to_take]
                remaining = packet.data[num_to_take:]

            if len(out) >= frame_count:
                return (out, pyaudio.paContinue)
            else:
                return (out, pyaudio.paComplete)

        try:
            self.output_stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                output=True,
                frames_per_buffer=self.chunk_size,
                stream_callback=_playback_callback
            )
            logger.info("Audio playback system ready")
        except Exception:
            logger.exception("Failed to initialize audio playback")
            raise

    def _get_and_increase_seq_num(self):
        seq = self.next_seq_num
        self.next_seq_num += 1
        return seq

    def queue_audio(self, audio_data: Optional[bytes]) -> None:
        """Queue audio data for playback."""
        self.playback_queue.put(
            AudioProcessor.AudioPlaybackPacket(
                seq_num=self._get_and_increase_seq_num(),
                data=audio_data))

    def skip_pending_audio(self):
        """Skip current audio in playback queue."""
        self.playback_base = self._get_and_increase_seq_num()

    def shutdown(self):
        """Clean up audio resources."""
        if self.input_stream:
            self.input_stream.stop_stream()
            self.input_stream.close()
            self.input_stream = None

        logger.info("Stopped audio capture")

        # Inform thread to complete
        if self.output_stream:
            self.skip_pending_audio()
            self.queue_audio(None)
            self.output_stream.stop_stream()
            self.output_stream.close()
            self.output_stream = None

        logger.info("Stopped audio playback")

        if self.audio:
            self.audio.terminate()

        logger.info("Audio processor cleaned up")


class BasicVoiceAssistant:
    """
        Basic voice assistant implementing the VoiceLive SDK patterns with Foundry Agent.
        This sample also demonstrates how to collect a conversation log of user and agent interactions.
    """

    def __init__(
        self,
        endpoint: str,
        credential: AsyncTokenCredential,
        agent_name: str,
        foundry_project_name: str,
        voice: str,
        foundry_resource_override: Optional[str] = None,
        agent_auth_identity_client_id: Optional[str] = None,
    ) -> None:

        self.endpoint = endpoint
        self.credential = credential
        self.agent_name = agent_name
        self.foundry_project_name = foundry_project_name
        self.voice = voice
        self.foundry_resource_override = foundry_resource_override
        self.agent_auth_identity_client_id = agent_auth_identity_client_id
        self.connection: Optional[VoiceLiveConnection] = None
        self.audio_processor: Optional[AudioProcessor] = None
        self.session_ready = False
        self.conversation_started = False

    async def start(self):
        """Start the voice assistant session."""
        try:
            logger.info("Connecting to VoiceLive API with Foundry agent connection %s for project %s", self.agent_name, self.foundry_project_name)

            # Connect to VoiceLive WebSocket API
            query_params: dict[str, str] = {
                "agent-name": self.agent_name,
                "agent-project-name": self.foundry_project_name,
            }
            if self.foundry_resource_override:
                query_params["foundry-resource-override"] = self.foundry_resource_override
            if self.agent_auth_identity_client_id:
                query_params["agent-authentication-identity-client-id"] = self.agent_auth_identity_client_id

            async with connect(
                endpoint=self.endpoint,
                credential=self.credential,
                query=query_params,
            ) as connection:
                conn = connection
                self.connection = conn

                # Initialize audio processor
                ap = AudioProcessor(conn)
                self.audio_processor = ap

                # Configure session for voice conversation
                await self._setup_session()

                # Start audio systems
                ap.start_playback()

                logger.info("Voice assistant ready! Start speaking...")
                print("\n" + "=" * 60)
                print("🎤 VOICE ASSISTANT READY")
                print("Start speaking to begin conversation")
                print("Press Ctrl+C to exit")
                print("=" * 60 + "\n")

                # Process events
                await self._process_events()
        except Exception:
            logger.exception("Voice assistant encountered an error")
            raise
        finally:
            if self.audio_processor:
                self.audio_processor.shutdown()

    async def _setup_session(self):
        """Configure the VoiceLive session for audio conversation."""
        logger.info("Setting up voice conversation session...")

        voice_config = AzureStandardVoice(name=self.voice)

        # Create strongly typed turn detection configuration
        turn_detection_config = ServerVad(
            threshold=0.5,
            prefix_padding_ms=300,
            silence_duration_ms=500)

        # # Set up interim response configuration
        # interim_response_config: InterimResponseConfig = LlmInterimResponseConfig(
        #     latency_threshold_ms=300,
        # )

        # Create strongly typed session configuration
        session_config = RequestSession(
            modalities=[Modality.TEXT, Modality.AUDIO],
            # voice=voice_config,
            input_audio_format=InputAudioFormat.PCM16,
            output_audio_format=OutputAudioFormat.PCM16,
            # turn_detection=turn_detection_config,
            # input_audio_echo_cancellation=AudioEchoCancellation(),
            # input_audio_noise_reduction=AudioNoiseReduction(type="azure_deep_noise_suppression"),
            # uncomment to use interim response if desired
            # interim_response=interim_response_config,
        )

        conn = self.connection
        assert conn is not None, "Connection must be established before setting up session"
        await conn.session.update(session=session_config)

        logger.info("Session configuration sent")

    async def _process_events(self):
        """Process events from the VoiceLive connection."""
        try:
            conn = self.connection
            assert conn is not None, "Connection must be established before processing events"
            async for event in conn:
                await self._handle_event(event)
        except Exception:
            logger.exception("Error processing events")
            raise

    async def _handle_event(self, event):
        """Handle different types of events from VoiceLive."""
        logger.debug("Received event: %s", event.type)
        ap = self.audio_processor
        conn = self.connection
        assert ap is not None, "AudioProcessor must be initialized"
        assert conn is not None, "Connection must be established"

        if event.type == ServerEventType.SESSION_UPDATED:
            logger.info("Session ready: %s", event.session.id)
            await write_conversation_log(f"SessionID: {event.session.id}")
            await write_conversation_log(f"Model: {event.session.model}")
            await write_conversation_log(f"Voice: {event.session.voice}")
            await write_conversation_log(f"")
            self.session_ready = True

            # Start audio capture once session is ready
            ap.start_capture()

        elif event.type == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
            user_transcript = f'User Input:\t{event.get("transcript", "")}'
            print("👤 You said: ", user_transcript)
            await write_conversation_log(user_transcript)

        elif event.type == ServerEventType.RESPONSE_TEXT_DONE:
            agent_text = f'Agent Text Response:\t{event.get("text", "")}'
            print("🤖 Agent responded with text: ", agent_text)
            await write_conversation_log(agent_text)

        elif event.type == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
            agent_audio = f'Agent Audio Response:\t{event.get("transcript", "")}'
            print("🤖 Agent responded with audio transcript: ", agent_audio)
            await write_conversation_log(agent_audio)

        elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
            logger.info("User started speaking - stopping playback")
            print("🎤 Listening...")

            # skip queued audio
            ap.skip_pending_audio()

        elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
            logger.info("🎤 User stopped speaking")
            print("🤔 Processing...")

        elif event.type == ServerEventType.RESPONSE_CREATED:
            logger.info("🤖 Assistant response created")

        elif event.type == ServerEventType.RESPONSE_AUDIO_DELTA:
            # Stream audio response to speakers
            logger.debug("Received audio delta")
            ap.queue_audio(event.delta)

        elif event.type == ServerEventType.RESPONSE_AUDIO_DONE:
            logger.info("🤖 Assistant finished speaking")

        elif event.type == ServerEventType.RESPONSE_DONE:
            logger.info("✅ Response complete")
            print("🎤 Ready for next input...")

        elif event.type == ServerEventType.ERROR:
            logger.error("❌ VoiceLive error: %s", event.error.message)
            print(f"Service returns error: {event.error}")

        elif event.type == ServerEventType.WARNING:
            logger.warning("⚠️ VoiceLive warning: %s", event.warning.message)
            print(f"Service returns warning: {event.warning}")

        elif event.type == ServerEventType.CONVERSATION_ITEM_CREATED:
            logger.debug("Conversation item created: %s", event.item.id)

        else:
            logger.debug("Unhandled event type: %s", event.type)

async def write_conversation_log(message: str) -> None:
    """Write a message to the conversation log."""
    def _write_to_file():
        with open(f'logs/{logfilename}', 'a', encoding='utf-8') as conversation_log:
            conversation_log.write(message + "\n")

    await asyncio.to_thread(_write_to_file)

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Basic Voice Assistant using Azure VoiceLive SDK",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--endpoint",
        help="Azure VoiceLive endpoint",
        type=str,
        default=os.environ.get("AZURE_VOICE_LIVE_ENDPOINT", "https://your-resource-name.services.ai.azure.com/"),
    )

    parser.add_argument(
        "--agent_name",
        help="Foundry agent name to use",
        type=str,
        default=os.environ.get("AZURE_VOICELIVE_AGENT_NAME", ""),
    )

    parser.add_argument(
        "--foundry_project_name",
        help="Foundry project name to use",
        type=str,
        default=os.environ.get("AZURE_VOICE_LIVE_PROJECT_NAME", ""),
    )

    parser.add_argument(
        "--voice",
        help="Voice to use for the assistant. E.g. en-US-Ava:DragonHDLatestNeural, en-US-GuyNeural",
        type=str,
        default=os.environ.get("AZURE_VOICELIVE_VOICE", "en-US-Ava:DragonHDLatestNeural"),
    )

    parser.add_argument("--verbose", help="Enable verbose logging", action="store_true")

    parser.add_argument(
        "--foundry_resource_override",
        help="(Optional) Foundry resource name for cross-resource agent mode",
        type=str,
        default=os.environ.get("AZURE_VOICELIVE_FOUNDRY_RESOURCE_OVERRIDE", None),
    )

    parser.add_argument(
        "--agent_auth_identity_client_id",
        help="(Optional) Client ID of user-assigned managed identity for agent authentication",
        type=str,
        default=os.environ.get("AZURE_VOICELIVE_AGENT_AUTH_IDENTITY_CLIENT_ID", None),
    )

    return parser.parse_args()


def main():
    """Main function."""
    args = parse_arguments()

    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create client with appropriate credential, only Entra ID token credential is allowed in Agent mode
    credential: AsyncTokenCredential = AzureCliCredential()  # or DefaultAzureCredential() if needed
    logger.info("Using Azure token credential")

    # Create and start voice assistant
    assistant = BasicVoiceAssistant(
        endpoint=args.endpoint,
        credential=credential,
        agent_name=args.agent_name,
        foundry_project_name=args.foundry_project_name,
        voice=args.voice,
        foundry_resource_override=args.foundry_resource_override,
        agent_auth_identity_client_id=args.agent_auth_identity_client_id,
    )

    # Setup signal handlers for graceful shutdown
    def signal_handler(_sig, _frame):
        logger.info("Received shutdown signal")
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start the assistant
    try:
        asyncio.run(assistant.start())
    except KeyboardInterrupt:
        print("\n👋 Voice assistant shut down. Goodbye!")
    except Exception as e:
        print("Fatal Error: ", e)

if __name__ == "__main__":
    # Check audio system
    try:
        p = pyaudio.PyAudio()
        # Check for input devices
        input_devices = [
            i
            for i in range(p.get_device_count())
            if cast(Union[int, float], p.get_device_info_by_index(i).get("maxInputChannels", 0) or 0) > 0
        ]
        # Check for output devices
        output_devices = [
            i
            for i in range(p.get_device_count())
            if cast(Union[int, float], p.get_device_info_by_index(i).get("maxOutputChannels", 0) or 0) > 0
        ]
        p.terminate()

        if not input_devices:
            print("❌ No audio input devices found. Please check your microphone.")
            sys.exit(1)
        if not output_devices:
            print("❌ No audio output devices found. Please check your speakers.")
            sys.exit(1)

    except Exception as e:
        print(f"❌ Audio system check failed: {e}")
        sys.exit(1)

    print("🎙️  Basic Voice Assistant with Azure VoiceLive SDK")
    print("=" * 50)

    # Run the assistant
    main()