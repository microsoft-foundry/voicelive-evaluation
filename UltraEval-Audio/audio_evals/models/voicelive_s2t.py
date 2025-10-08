import os
import re
import sys
import wave
import numpy as np
import asyncio
import base64
import logging
import threading
import queue
import tempfile
from typing import Union, Optional, TYPE_CHECKING
from concurrent.futures import ThreadPoolExecutor
from pydub import AudioSegment


from azure.core.credentials import AzureKeyCredential
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import AzureDeveloperCliCredential, DefaultAzureCredential
from azure.ai.voicelive.aio import connect
from azure.ai.voicelive.models import (
    RequestSession,
    ServerVad,
    AzureStandardVoice,
    Modality,
    InputAudioFormat,
    OutputAudioFormat,
    ServerEventType,
    AudioInputTranscriptionOptions,
)

from audio_evals.models.model import APIModel
from audio_evals.base import PromptStruct
from dotenv import load_dotenv
load_dotenv()


def sanitize_text_for_utf8(sanitizetext: str) -> str:
    """
    Sanitize text to ensure valid UTF-8 encoding and remove problematic characters.
    This prevents encoding issues when writing to JSON files.
    """
    if not isinstance(sanitizetext, str) or not sanitizetext:
        return sanitizetext or ""

    try:
        # Replace smart quotes and other problematic Unicode characters with ASCII equivalents
        replacements = {
            # Smart quotes -> ASCII quotes
            '\u2018': "'",  # Left single quotation mark
            '\u2019': "'",  # Right single quotation mark  
            '\u201A': "'",  # Single low-9 quotation mark
            '\u201B': "'",  # Single high-reversed-9 quotation mark
            '\u201C': '"',  # Left double quotation mark
            '\u201D': '"',  # Right double quotation mark
            '\u201E': '"',  # Double low-9 quotation mark
            '\u201F': '"',  # Double high-reversed-9 quotation mark
            # Dashes -> ASCII dash/hyphen
            '\u2013': '-',  # En dash
            '\u2014': '-',  # Em dash
            '\u2015': '-',  # Horizontal bar
            # Other common problematic characters
            '\u2026': '...',  # Horizontal ellipsis
            '\u00A0': ' ',   # Non-breaking space
        }
        
        for unicode_char, ascii_replacement in replacements.items():
            sanitizetext = sanitizetext.replace(unicode_char, ascii_replacement)
        
        # Remove control characters and non-printable characters
        sanitizetext = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', sanitizetext)

        # Replace common problematic characters that might cause encoding issues
        sanitizetext = sanitizetext.replace('\ufffd', '')  # Remove replacement character
        sanitizetext = sanitizetext.replace('\u0000', '')  # Remove null character

        # Ensure the text can be properly encoded as UTF-8
        sanitizetext = sanitizetext.encode('utf-8', errors='replace').decode('utf-8')

        # Normalize whitespace
        sanitizetext = re.sub(r'\s+', ' ', sanitizetext).strip()

        return sanitizetext
    except (UnicodeEncodeError, UnicodeDecodeError, AttributeError):
        # Fallback: convert to ASCII only
        try:
            return sanitizetext.encode('ascii', errors='ignore').decode('ascii').strip()
        except:
            return ""

import threading
import time

_concurrency_lock = threading.Lock()
_active_calls = 0

def _inc_active():
    global _active_calls
    with _concurrency_lock:
        _active_calls += 1
        return _active_calls

def _dec_active():
    global _active_calls
    with _concurrency_lock:
        _active_calls -= 1
        return _active_calls


if TYPE_CHECKING:
    from azure.ai.voicelive.aio import VoiceLiveConnection

logger = logging.getLogger(__name__)

class AudioProcessor:
    """
    Handles audio capture from WAV files and robust playback for the voice assistant.

    Threading Architecture:
    - Main thread: Event loop coordination
    - Capture thread: WAV file reading and audio processing  
    - Send thread: Async audio data transmission to VoiceLive
    - Playback thread: Audio data writing to output WAV file
    """
    
    class AudioPlaybackPacket:
        """Represents a packet that can be sent to the audio playback queue."""
        def __init__(self, seq_num: int, data: Optional[bytes]):
            self.seq_num = seq_num
            self.data = data

    def __init__(self, connection, wav_path: str, reply_wav_path: str = "reply_output.wav"):
        self.connection = connection
        self.wav_path = wav_path
        self.reply_wav_path = reply_wav_path
        self.reply_wav_file = None
        self.channels = 1
        self.rate = 24000
        self.chunk_size = 1024
        self.sampwidth = 2
        self.is_capturing = False
        self.is_playing = False
        
        # Improved playback queue system with sequencing
        self.playback_queue: "queue.Queue[AudioProcessor.AudioPlaybackPacket]" = queue.Queue()
        self.playback_base = 0
        self.next_seq_num = 0
        
        self.audio_send_queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.capture_thread: Optional[threading.Thread] = None
        self.playback_thread: Optional[threading.Thread] = None
        self.send_thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        
        logger.info("AudioProcessor initialized for WAV file processing with improved playback system")

    async def start_capture(self):
        if self.is_capturing:
            return
        self.loop = asyncio.get_event_loop()
        self.is_capturing = True
        self.capture_thread = threading.Thread(target=self._capture_wav_thread, daemon=True)
        self.capture_thread.start()
        self.send_thread = threading.Thread(target=self._send_audio_thread, daemon=True)
        self.send_thread.start()

    def _capture_wav_thread(self):
        try:
            with wave.open(self.wav_path, 'rb') as wf:
                orig_rate, channels, sampwidth = wf.getframerate(), wf.getnchannels(), wf.getsampwidth()
                if sampwidth != 2:
                    logger.error("Only 16-bit PCM WAV files are supported.")
                    return
                audio_bytes = wf.readframes(wf.getnframes())
                audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
                if channels > 1:
                    audio_np = audio_np[::channels]
                if orig_rate != self.rate:
                    from scipy.signal import resample_poly
                    audio_np = resample_poly(audio_np, self.rate, orig_rate).astype(np.int16)
                idx, total = 0, len(audio_np)
                while self.is_capturing and idx < total:
                    chunk = audio_np[idx:idx+self.chunk_size]
                    idx += self.chunk_size
                    self.audio_send_queue.put(base64.b64encode(chunk.tobytes()).decode("utf-8"))
            self.audio_send_queue.put(None)
        except Exception as e:
            logger.error(f"Failed to read WAV file: {e}")

    def _send_audio_thread(self):
        while self.is_capturing:
            try:
                audio_base64 = self.audio_send_queue.get(timeout=1.0)
                if audio_base64 is None:
                    break
                if self.loop:
                    asyncio.run_coroutine_threadsafe(
                        self.connection.input_audio_buffer.append(audio=audio_base64), self.loop
                    )
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Failed to send audio: {e}")
                break

    async def stop_capture(self):
        if not self.is_capturing:
            return
        self.is_capturing = False
        if self.capture_thread:
            self.capture_thread.join(timeout=1.0)
        if self.send_thread:
            self.send_thread.join(timeout=1.0)
        with self.audio_send_queue.mutex:
            self.audio_send_queue.queue.clear()

    async def start_playback(self):
        """Initialize improved audio playback system with sequencing."""
        if self.is_playing:
            return
        self.is_playing = True
        self.reply_wav_file = wave.open(self.reply_wav_path, 'wb')
        self.reply_wav_file.setnchannels(self.channels)
        self.reply_wav_file.setsampwidth(self.sampwidth)
        self.reply_wav_file.setframerate(self.rate)
        self.playback_thread = threading.Thread(target=self._playback_audio_thread, daemon=True)
        self.playback_thread.start()
        logger.info("Audio playback system ready")

    def _playback_audio_thread(self):
        """Improved playback thread with packet sequencing and skip handling."""
        remaining_data = bytes()
        
        while self.is_playing:
            try:
                packet = self.playback_queue.get(timeout=0.1)
                
                if not packet or not packet.data:
                    # None packet indicates end of stream
                    logger.info("End of playback queue.")
                    break
                
                if packet.seq_num < self.playback_base:
                    # Skip requested packet - ignore and clear any remaining data
                    if len(remaining_data) > 0:
                        remaining_data = bytes()
                    continue
                
                # Write audio data to WAV file
                if self.reply_wav_file:
                    self.reply_wav_file.writeframes(packet.data)
                    
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in audio playback: {e}")
                break

    def _get_and_increase_seq_num(self):
        """Get next sequence number for audio packets."""
        seq = self.next_seq_num
        self.next_seq_num += 1
        return seq

    async def queue_audio(self, audio_data: Optional[bytes]) -> None:
        """Queue audio data for playback with improved packet system."""
        if self.is_playing:
            self.playback_queue.put(
                AudioProcessor.AudioPlaybackPacket(
                    seq_num=self._get_and_increase_seq_num(),
                    data=audio_data))

    def skip_pending_audio(self):
        """Skip current audio in playback queue - improved interruption handling."""
        self.playback_base = self._get_and_increase_seq_num()

    async def stop_playback(self):
        """Stop playback with improved cleanup."""
        if not self.is_playing:
            return
        self.is_playing = False
        
        # Signal end of playback and cleanup
        if hasattr(self, 'playback_queue'):
            self.skip_pending_audio()
            await self.queue_audio(None)
            
        if self.playback_thread:
            self.playback_thread.join(timeout=1.0)
        if self.reply_wav_file:
            self.reply_wav_file.close()
            self.reply_wav_file = None
        logger.info("Stopped audio playback")

    async def cleanup(self):
        """Improved cleanup with better resource management and timeout handling."""
        try:
            # Stop capture and playback with timeout protection
            await asyncio.wait_for(self.stop_capture(), timeout=2.0)
        except asyncio.TimeoutError:
            logger.warning("Stop capture timed out during cleanup")
        except Exception as e:
            logger.warning(f"Error stopping capture during cleanup: {e}")
            
        try:
            await asyncio.wait_for(self.stop_playback(), timeout=2.0)
        except asyncio.TimeoutError:
            logger.warning("Stop playback timed out during cleanup")
        except Exception as e:
            logger.warning(f"Error stopping playback during cleanup: {e}")
            
        try:
            # Shutdown executor with timeout
            self.executor.shutdown(wait=False)  # Don't block on Windows
            logger.info("Audio processor cleaned up")
        except Exception as e:
            logger.warning(f"Error shutting down executor: {e}")


class BasicVoiceAssistant:
    def __init__(self, endpoint: str, credential: Union[AzureKeyCredential, AsyncTokenCredential],
                 model: str, transcriptionmodel: str, voice: str, instructions: str, wav_path: Optional[str] = None, reply_wav_path: Optional[str] = None):
        self.endpoint, self.credential, self.model, self.transcriptionmodel, self.voice, self.instructions, self.wav_path, self.reply_wav_path = \
            endpoint, credential, model, transcriptionmodel, voice, instructions, wav_path, reply_wav_path
        self.connection: Optional["VoiceLiveConnection"] = None
        self.audio_processor: Optional[AudioProcessor] = None
        self.transcript: str = ""
        self.inputtranscript: str = ""
        self.barge_in: bool = False  # Track if user interrupted the assistant
        self.assistant_responding: bool = False  # Track if assistant is currently responding

    async def start(self):
        """Start the voice assistant session with improved error handling and connection management."""
        try:
            logger.info(f"Connecting to VoiceLive API with model {self.model}")
            
            # Connect to VoiceLive WebSocket API with improved connection options
            # Remove connection_options to use defaults and avoid type issues
            async with connect(
                endpoint=self.endpoint, 
                credential=self.credential, 
                model=self.model
            ) as conn:
                self.connection = conn
                
                # Initialize audio processor with robust configuration
                if not self.wav_path or not self.reply_wav_path:
                    raise ValueError("WAV file paths must be specified for audio processing")
                    
                self.audio_processor = AudioProcessor(conn, wav_path=self.wav_path, reply_wav_path=self.reply_wav_path)
                
                # Configure session and start processing
                await self._setup_session()
                await self.audio_processor.start_playback()
                
                logger.info("Voice assistant ready for processing...")
                await self._process_events()
                
        except asyncio.CancelledError:
            logger.info("Voice assistant session was cancelled")
            raise
        except ConnectionError as e:
            logger.error(f"Connection error in voice assistant session: {e}")
            raise
        except Exception as e:
            logger.error(f"Error in voice assistant session: {e}")
            raise
        finally:
            # Ensure cleanup happens even if connection was aborted
            if self.audio_processor:
                try:
                    await asyncio.wait_for(self.audio_processor.cleanup(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("Audio processor cleanup timed out")
                except Exception as cleanup_error:
                    logger.warning(f"Error during audio processor cleanup: {cleanup_error}")

    async def _setup_session(self):
        """Configure the VoiceLive session with improved robustness."""
        logger.info("Setting up voice conversation session...")
        
        # Create strongly typed voice configuration with improved handling
        voice_config: Union[AzureStandardVoice, str]
        if self.voice.startswith("en-US-") or self.voice.startswith("en-CA-") or "-" in self.voice:
            # Azure voice
            voice_config = AzureStandardVoice(name=self.voice)
        else:
            # OpenAI voice (alloy, echo, fable, onyx, nova, shimmer)
            voice_config = self.voice

        # Create strongly typed turn detection configuration with improved settings
        turn_detection_config = ServerVad(
            threshold=0.5,
            prefix_padding_ms=300,
            silence_duration_ms=500)

        # Create strongly typed session configuration with enhanced options
        session_config = RequestSession(
            modalities=[Modality.TEXT, Modality.AUDIO],
            instructions=self.instructions,
            voice=voice_config,
            input_audio_format=InputAudioFormat.PCM16,
            output_audio_format=OutputAudioFormat.PCM16,
            turn_detection=turn_detection_config,
            input_audio_transcription=AudioInputTranscriptionOptions(model=self.transcriptionmodel)
        )
        
        logger.info(f"Session config: {session_config}")    
        await self.connection.session.update(session=session_config)
        logger.info("Session configuration sent")

    async def _process_events(self):
        """Process events from the VoiceLive connection with improved error handling."""
        try:
            async for event in self.connection:
                logger.debug(f"Received event: {event.type}")
                await self._handle_event(event)
                if self.wav_path and event.type == ServerEventType.RESPONSE_DONE:
                    logger.info("Response processing complete, ending session")
                    break
        except Exception as e:
            logger.error(f"Error processing events: {e}")
            raise

    async def _handle_event(self, event):
        ap = self.audio_processor
        conn = self.connection
        if event.type == ServerEventType.SESSION_UPDATED:
            await ap.start_capture()
        elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
            # Check if this is a barge-in (user interrupting assistant response)
            if self.assistant_responding:
                self.barge_in = True
                logger.info("BARGE-IN DETECTED: User interrupted assistant response")
            else:
                logger.info("User started speaking - stopping playback and skipping pending audio")
            
            # Improved interruption handling with skip_pending_audio
            ap.skip_pending_audio()
            # try:
            #     await conn.response.cancel()
            # except Exception as e:
            #     logger.debug(f"Response cancellation failed (non-critical): {e}")
            #     pass
        elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
            logger.info("User stopped speaking - ready for response")
            await ap.start_playback()
        elif event.type == ServerEventType.RESPONSE_CREATED:
            logger.info("Assistant response created - starting response phase")
            self.assistant_responding = True
        elif event.type == ServerEventType.RESPONSE_AUDIO_DELTA:
            await ap.queue_audio(event.delta)
        elif event.type == ServerEventType.RESPONSE_DONE:
            logger.info("Assistant response complete")
            self.assistant_responding = False
        ### Retrieve conversation_item_transcript from event
        elif event.type == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
            logger.debug(f"Received input audio transcription completed.")
            self.inputtranscript = event.get('transcript', '')
            logger.debug(f"User said: {self.inputtranscript}")
        elif event.type == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
            logger.debug(f"Received audio transcript done.")
            self.transcript = event.get('transcript', '')
            logger.debug(f"Assistant said: : {self.transcript}")
        ### End retrieve conversation_item_transcript

def run_async_in_thread(coro):
    """
    Run coroutine in this thread with improved error handling and cleanup.
    If no loop exists, create one and ensure proper cleanup even on connection failures.
    If a running loop exists (rare in ThreadPool worker), schedule via run_coroutine_threadsafe.
    """
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        # no running loop in this thread -> create one, run, then close it
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            return loop.run_until_complete(coro)
        except Exception as e:
            logger.error(f"Coroutine execution failed: {e}")
            raise
        finally:
            # Improved cleanup to handle Windows I/O completion port issues
            try:
                # Cancel all pending tasks
                pending_tasks = [task for task in asyncio.all_tasks(loop) if not task.done()]
                if pending_tasks:
                    logger.debug(f"Cancelling {len(pending_tasks)} pending tasks")
                    for task in pending_tasks:
                        task.cancel()
                    
                    # Wait for tasks to complete cancellation
                    if pending_tasks:
                        loop.run_until_complete(asyncio.gather(*pending_tasks, return_exceptions=True))
                
                # Shutdown async generators
                loop.run_until_complete(loop.shutdown_asyncgens())
                
                # Give time for Windows I/O operations to complete
                import time
                time.sleep(0.1)
                
            except Exception as cleanup_error:
                logger.warning(f"Error during loop cleanup: {cleanup_error}")
            finally:
                try:
                    loop.close()
                except Exception as close_error:
                    logger.warning(f"Error closing event loop: {close_error}")
                finally:
                    asyncio.set_event_loop(None)
    else:
        # there is a running loop in this thread (unusual) -> submit safely
        try:
            fut = asyncio.run_coroutine_threadsafe(coro, running_loop)
            return fut.result()
        except Exception as e:
            logger.error(f"Coroutine execution in existing loop failed: {e}")
            raise

class VoiceLiveS2TModel(APIModel):
    # Class-level shared credentials to avoid recreating them for each request
    _shared_credential = None
    _credential_lock = threading.Lock()
    
    #def __init__(self, api_key, endpoint, model, voice, instructions, use_token_credential=False, sample_params=None):
    def __init__(self, voice, instructions, use_token_credential=True, sample_params=None):
        super().__init__(True, sample_params)
        self.api_key = os.environ.get("AZURE_VOICELIVE_API_KEY")
        self.endpoint = os.environ.get("AZURE_VOICELIVE_ENDPOINT")
        self.model = os.environ.get("AZURE_VOICELIVE_MODEL", "gpt-realtime")
        self.transcriptionmodel = os.environ.get("AZURE_VOICELIVE_TRANSCRIPTION_MODEL", "gpt-4o-transcribe")
        self.voice = voice or os.environ.get("AZURE_VOICELIVE_VOICE")
        self.instructions = instructions or os.environ.get("AZURE_VOICELIVE_INSTRUCTIONS")
        self.use_token_credential = use_token_credential

        logger.info(
            f"VoiceLiveS2TModel initialized:\n"
            f"  endpoint={self.endpoint}\n"
            f"  model={self.model}\n"
            f"  transcriptionmodel={self.transcriptionmodel}\n"
            f"  voice={self.voice}\n"
            f"  instructions={self.instructions[:30]}..."
        )
        
        # Initialize shared credential on first instance
        self._ensure_credential_initialized()
    
    def _ensure_credential_initialized(self):
        """Initialize shared credential if not already done (thread-safe)"""
        with VoiceLiveS2TModel._credential_lock:
            if VoiceLiveS2TModel._shared_credential is None:
                if self.use_token_credential:
                    VoiceLiveS2TModel._shared_credential = DefaultAzureCredential()
                    logger.info("Initialized shared DefaultAzureCredential for VoiceLive S2T")
                else:
                    VoiceLiveS2TModel._shared_credential = AzureKeyCredential(self.api_key)
                    logger.info("Initialized shared AzureKeyCredential for VoiceLive S2T")
    
    def _get_credential(self):
        """Get the shared credential instance"""
        return VoiceLiveS2TModel._shared_credential

    def _inference(self, prompt: PromptStruct, **kwargs):
        thread_name = threading.current_thread().name
        start_ts = time.time()
        cur = _inc_active()
        logger.info(f"[VoiceLiveS2T] START thread={thread_name} ts={start_ts:.3f} active={cur}")

        logger.info(prompt)
        audio_file = ""
        for content in prompt:
            if content["role"] == "user":
                for line in content["contents"]:
                    if line["type"] == "audio":
                        audio_file = line["value"]
                        break

        if not audio_file:
            _dec_active()
            raise ValueError("No audio file found in the prompt.")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as padded_wav:
            padded_wav_path = padded_wav.name

        audio = AudioSegment.from_wav(audio_file)
        silence = AudioSegment.silent(duration=2000, frame_rate=audio.frame_rate)
        padded_audio = audio + silence
        padded_audio.export(padded_wav_path, format="wav")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as reply_wav:
            reply_wav_path = reply_wav.name

        credential = self._get_credential()
        instructions = self.instructions
        assistant = BasicVoiceAssistant(
            self.endpoint, credential, self.model, self.transcriptionmodel, self.voice, instructions,
            wav_path=padded_wav_path, reply_wav_path=reply_wav_path
        )
        text = ""
        input_text = ""
        barge_in = False  # Initialize barge_in flag
        try:
            # run assistant (will block this worker thread) with improved error handling
            try:
                logger.info("Starting VoiceLive assistant...")
                run_async_in_thread(assistant.start())
                text = assistant.transcript
                input_text = assistant.inputtranscript
                barge_in = assistant.barge_in
                logger.info("VoiceLive assistant completed successfully")
                        
            except ConnectionError as ce:
                logger.error(f"VoiceLive connection error: {ce}")
                raise
            except OSError as oe:
                logger.error(f"VoiceLive I/O error (possibly Windows completion port issue): {oe}")
                # Don't re-raise OSError as it might be recoverable
                text = ""
                input_text = ""
                barge_in = False
            except Exception as e:
                logger.exception(f"VoiceLive assistant failed: {e}")
                raise
        finally:
            # clean padded input file
            try:
                if os.path.exists(padded_wav_path):
                    os.remove(padded_wav_path)
            except Exception:
                pass

            end_ts = time.time()
            cur = _dec_active()
            
            # Sanitize texts to ensure valid UTF-8 encoding
            # text = sanitize_text_for_utf8(text).strip()
            # input_text = sanitize_text_for_utf8(input_text).strip()
            # text = text.encode('utf-8', errors='replace').decode('utf-8')
            # input_text = input_text.encode('utf-8', errors='replace').decode('utf-8')
            text = text.strip()
            input_text = input_text.strip()
            logger.info({"audio": reply_wav_path, "text": text, "input_text": input_text, "barge-in": barge_in})
            logger.info(f"[VoiceLiveS2T] END   thread={thread_name} ts={end_ts:.3f} elapsed={(end_ts-start_ts):.3f}s active={cur}")

        return {"audio": reply_wav_path, "text": text, "input_text": input_text, "barge-in": barge_in}
