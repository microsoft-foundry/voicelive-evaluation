import os
import re
import sys
import wave
import whisper

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


from azure.core.credentials import AzureKeyCredential, TokenCredential
from azure.identity import InteractiveBrowserCredential
from azure.ai.voicelive.aio import connect
from azure.ai.voicelive.models import (
    RequestSession,
    ServerVad,
    AzureStandardVoice,
    Modality,
    AudioFormat,
    ServerEventType,
)

from audio_evals.models.model import APIModel
from audio_evals.base import PromptStruct
from dotenv import load_dotenv
load_dotenv()

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

asr_model = whisper.load_model("turbo") 
_asr_lock = threading.Lock()

class AudioProcessor:
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
        self.audio_queue: "queue.Queue[bytes]" = queue.Queue()
        self.audio_send_queue: "queue.Queue[str]" = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.capture_thread: Optional[threading.Thread] = None
        self.playback_thread: Optional[threading.Thread] = None
        self.send_thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None

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
        if self.is_playing:
            return
        self.is_playing = True
        self.reply_wav_file = wave.open(self.reply_wav_path, 'wb')
        self.reply_wav_file.setnchannels(self.channels)
        self.reply_wav_file.setsampwidth(self.sampwidth)
        self.reply_wav_file.setframerate(self.rate)
        self.playback_thread = threading.Thread(target=self._playback_audio_thread, daemon=True)
        self.playback_thread.start()

    def _playback_audio_thread(self):
        while self.is_playing:
            try:
                audio_data = self.audio_queue.get(timeout=0.1)
                if audio_data and self.reply_wav_file:
                    self.reply_wav_file.writeframes(audio_data)
            except queue.Empty:
                continue

    async def queue_audio(self, audio_data: bytes):
        if self.is_playing:
            self.audio_queue.put(audio_data)

    async def stop_playback(self):
        if not self.is_playing:
            return
        self.is_playing = False
        if self.playback_thread:
            self.playback_thread.join(timeout=1.0)
        if self.reply_wav_file:
            self.reply_wav_file.close()
            self.reply_wav_file = None

    async def cleanup(self):
        await self.stop_capture()
        await self.stop_playback()
        self.executor.shutdown(wait=True)


class BasicVoiceAssistant:
    def __init__(self, endpoint: str, credential: Union[AzureKeyCredential, TokenCredential],
                 model: str, voice: str, instructions: str, wav_path: Optional[str] = None, reply_wav_path: Optional[str] = None):
        self.endpoint, self.credential, self.model, self.voice, self.instructions, self.wav_path, self.reply_wav_path = \
            endpoint, credential, model, voice, instructions, wav_path, reply_wav_path
        self.connection: Optional["VoiceLiveConnection"] = None
        self.audio_processor: Optional[AudioProcessor] = None

    async def start(self):
        try:
            async with connect(endpoint=self.endpoint, credential=self.credential, model=self.model,
                               connection_options={"max_msg_size": 10 * 1024 * 1024, "heartbeat": 20, "timeout": 20}) as conn:
                self.connection = conn
                self.audio_processor = AudioProcessor(conn, wav_path=self.wav_path, reply_wav_path=self.reply_wav_path)
                await self._setup_session()
                await self.audio_processor.start_playback()
                await self._process_events()
        finally:
            if self.audio_processor:
                await self.audio_processor.cleanup()

    async def _setup_session(self):
        voice_config = AzureStandardVoice(name=self.voice, type="azure-standard") \
            if "-" in self.voice else self.voice
        session_config = RequestSession(
            modalities=[Modality.TEXT, Modality.AUDIO],
            instructions=self.instructions,
            voice=voice_config,
            input_audio_format=AudioFormat.PCM16,
            output_audio_format=AudioFormat.PCM16,
            turn_detection=ServerVad(threshold=0.5, prefix_padding_ms=300, silence_duration_ms=500),
        )
        await self.connection.session.update(session=session_config)

    async def _process_events(self):
        async for event in self.connection:
            await self._handle_event(event)
            if self.wav_path and event.type == ServerEventType.RESPONSE_DONE:
                break

    async def _handle_event(self, event):
        ap = self.audio_processor
        conn = self.connection
        if event.type == ServerEventType.SESSION_UPDATED:
            await ap.start_capture()
        elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
            await ap.stop_playback()
            #try:
            #    await conn.response.cancel()
            #except Exception:
            #    pass
        elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
            await ap.start_playback()
        elif event.type == ServerEventType.RESPONSE_AUDIO_DELTA:
            await ap.queue_audio(event.delta)

def run_async_in_thread(coro):
    """
    Run coroutine in this thread. If no loop exists, create one and close it after running.
    If a running loop exists (rare in ThreadPool worker), schedule via run_coroutine_threadsafe.
    """
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        # no running loop in this thread -> create one, run, then close it
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
            asyncio.set_event_loop(None)
    else:
        # there is a running loop in this thread (unusual) -> submit safely
        try:
            fut = asyncio.run_coroutine_threadsafe(coro, running_loop)
            return fut.result()
        except Exception as e:
            raise

class VoiceLiveS2SModel(APIModel):
    #def __init__(self, api_key, endpoint, model, voice, instructions, use_token_credential=False, sample_params=None):
    def __init__(self, voice, instructions, use_token_credential=False, sample_params=None):
        super().__init__(True, sample_params)
        self.api_key = os.environ.get("AZURE_VOICELIVE_API_KEY")
        self.endpoint = os.environ.get("AZURE_VOICELIVE_ENDPOINT")
        self.model = os.environ.get("VOICELIVE_MODEL")
        self.voice = voice or os.environ.get("VOICELIVE_VOICE")
        self.instructions = instructions or os.environ.get("VOICELIVE_INSTRUCTIONS")
        print(self.voice)
        
        self.use_token_credential = use_token_credential

    def _inference(self, prompt: PromptStruct, **kwargs):
        thread_name = threading.current_thread().name
        start_ts = time.time()
        cur = _inc_active()
        logger.info(f"[VoiceLiveS2S] START thread={thread_name} ts={start_ts:.3f} active={cur}")

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

        credential = InteractiveBrowserCredential() if self.use_token_credential else AzureKeyCredential(self.api_key)
        instructions = self.instructions
        assistant = BasicVoiceAssistant(
            self.endpoint, credential, self.model, self.voice, instructions,
            wav_path=padded_wav_path, reply_wav_path=reply_wav_path
        )
        text = ""
        try:
            # run assistant (will block this worker thread)
            try:
                run_async_in_thread(assistant.start())
            except Exception:
                logger.exception("VoiceLive assistant failed")
                raise

            # Transcribe with lock to protect shared GPU model
            if asr_model is None:
                logger.warning("ASR model not available, returning empty text")
                text = ""
            else:
                try:
                    with _asr_lock:
                        text = asr_model.transcribe(reply_wav_path)["text"].strip()
                except Exception:
                    logger.exception("ASR transcribe failed")
                    text = ""
        finally:
            # clean padded input file
            try:
                if os.path.exists(padded_wav_path):
                    os.remove(padded_wav_path)
            except Exception:
                pass

            end_ts = time.time()
            cur = _dec_active()
            logger.info(f"[VoiceLiveS2S] END   thread={thread_name} ts={end_ts:.3f} elapsed={(end_ts-start_ts):.3f}s active={cur}")

        return {"audio": reply_wav_path, "text": text}
