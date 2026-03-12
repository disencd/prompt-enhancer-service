"""Voice capture — microphone recording with Voice Activity Detection."""

from __future__ import annotations

import asyncio
import io
import logging
import tempfile
import wave
from enum import Enum
from pathlib import Path

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
# VAD operates on 30ms frames
FRAME_DURATION_MS = 30
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)


class CaptureState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"


class VoiceCapture:
    """Records audio from the microphone with VAD-based endpoint detection."""

    def __init__(
        self,
        silence_threshold_sec: float = 1.0,
        max_duration_sec: float = 30.0,
        vad_aggressiveness: int = 2,
    ):
        self._silence_threshold = silence_threshold_sec
        self._max_duration = max_duration_sec
        self._vad_aggressiveness = vad_aggressiveness
        self._state = CaptureState.IDLE
        self._cancel_event: asyncio.Event | None = None

    @property
    def state(self) -> CaptureState:
        return self._state

    async def capture(self) -> bytes | None:
        """Record audio until silence is detected or max duration is reached.

        Returns WAV file bytes, or None if cancelled / no speech detected.
        """
        self._state = CaptureState.LISTENING
        self._cancel_event = asyncio.Event()

        try:
            audio_data = await self._record_with_vad()
            if audio_data is None or len(audio_data) < SAMPLE_RATE:
                logger.info("No speech detected or recording too short")
                return None
            self._state = CaptureState.PROCESSING
            return self._to_wav(audio_data)
        except asyncio.CancelledError:
            logger.info("Voice capture cancelled")
            return None
        finally:
            self._state = CaptureState.IDLE

    def cancel(self) -> None:
        """Cancel an ongoing capture."""
        if self._cancel_event:
            self._cancel_event.set()

    async def _record_with_vad(self) -> np.ndarray | None:
        """Record with energy-based voice activity detection."""
        loop = asyncio.get_event_loop()

        frames: list[np.ndarray] = []
        speech_started = False
        silence_frames = 0
        silence_limit = int(self._silence_threshold / (FRAME_DURATION_MS / 1000))
        max_frames = int(self._max_duration * 1000 / FRAME_DURATION_MS)

        # Use energy-based VAD (simpler, avoids webrtcvad C dependency issues)
        energy_threshold = 500  # Tunable; will auto-adjust

        # Calibrate noise floor from first 0.5s
        calibration_frames = int(500 / FRAME_DURATION_MS)
        noise_energies: list[float] = []

        def _frame_energy(frame: np.ndarray) -> float:
            return float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))

        logger.info("Listening... (speak now)")

        # Record in a thread to avoid blocking the event loop
        audio_queue: asyncio.Queue[np.ndarray | None] = asyncio.Queue()

        def _audio_callback(indata, frame_count, time_info, status):
            if status:
                logger.debug("Audio status: %s", status)
            loop.call_soon_threadsafe(audio_queue.put_nowait, indata.copy())

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=FRAME_SIZE,
            callback=_audio_callback,
        )

        try:
            stream.start()
            frame_count = 0

            while frame_count < max_frames:
                # Check for cancellation
                if self._cancel_event and self._cancel_event.is_set():
                    return None

                try:
                    frame = await asyncio.wait_for(audio_queue.get(), timeout=0.1)
                except TimeoutError:
                    continue

                flat = frame.flatten()
                energy = _frame_energy(flat)
                frames.append(flat)
                frame_count += 1

                # Calibration phase
                if frame_count <= calibration_frames:
                    noise_energies.append(energy)
                    if frame_count == calibration_frames:
                        noise_floor = np.mean(noise_energies)
                        energy_threshold = max(noise_floor * 3, 300)
                        logger.debug(
                            "Noise floor: %.1f, threshold: %.1f",
                            noise_floor,
                            energy_threshold,
                        )
                    continue

                # VAD logic
                is_speech = energy > energy_threshold

                if is_speech:
                    speech_started = True
                    silence_frames = 0
                elif speech_started:
                    silence_frames += 1
                    if silence_frames >= silence_limit:
                        logger.info(
                            "Silence detected after speech (%.1fs)",
                            frame_count * FRAME_DURATION_MS / 1000,
                        )
                        break

        finally:
            stream.stop()
            stream.close()

        if not speech_started:
            return None

        return np.concatenate(frames)

    def _to_wav(self, audio: np.ndarray) -> bytes:
        """Convert numpy int16 audio to WAV bytes."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # int16 = 2 bytes
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio.tobytes())
        return buf.getvalue()

    def save_debug_wav(self, wav_bytes: bytes, path: str | None = None) -> Path:
        """Save WAV bytes to a file for debugging."""
        if path is None:
            fd, path = tempfile.mkstemp(suffix=".wav", prefix="prompt_pulse_")
        p = Path(path)
        p.write_bytes(wav_bytes)
        logger.debug("Saved debug audio to %s", p)
        return p
