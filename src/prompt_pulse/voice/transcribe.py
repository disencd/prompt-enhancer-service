"""Speech-to-text transcription engine with multiple backend support."""

from __future__ import annotations

import logging
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


class TranscriptionResult:
    """Result of a transcription operation."""

    def __init__(self, text: str, language: str = "en", confidence: float = 1.0):
        self.text = text.strip()
        self.language = language
        self.confidence = confidence

    def __str__(self) -> str:
        return self.text

    def __bool__(self) -> bool:
        return bool(self.text)


class TranscriptionEngine(ABC):
    """Abstract base class for transcription backends."""

    @abstractmethod
    async def transcribe(self, wav_bytes: bytes) -> TranscriptionResult:
        """Transcribe WAV audio bytes to text."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this engine is available on the system."""
        ...


class WhisperLocalEngine(TranscriptionEngine):
    """Local Whisper transcription via faster-whisper."""

    def __init__(self, model_size: str = "base.en"):
        self._model_size = model_size
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel

            logger.info(
                "Loading Whisper model '%s' (first load may download ~150MB)...",
                self._model_size,
            )
            self._model = WhisperModel(
                self._model_size,
                device="cpu",
                compute_type="int8",
            )
            logger.info("Whisper model loaded successfully")
        except Exception:
            logger.exception("Failed to load Whisper model")
            raise

    async def transcribe(self, wav_bytes: bytes) -> TranscriptionResult:
        """Transcribe using local faster-whisper model."""
        self._load_model()

        # Write to temp file (faster-whisper needs a file path)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name

        try:
            segments, info = self._model.transcribe(
                tmp_path,
                beam_size=5,
                language="en",
                vad_filter=True,
            )
            text = " ".join(seg.text for seg in segments).strip()
            conf = (
                1.0 - info.language_probability
                if info.language != "en"
                else info.language_probability
            )
            return TranscriptionResult(
                text=text,
                language=info.language,
                confidence=conf,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def is_available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401

            return True
        except ImportError:
            return False


class WhisperAPIEngine(TranscriptionEngine):
    """Cloud-based transcription via OpenAI Whisper API."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key

    async def transcribe(self, wav_bytes: bytes) -> TranscriptionResult:
        """Transcribe using OpenAI Whisper API."""
        import httpx

        api_key = self._api_key
        if not api_key:
            import os

            api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OpenAI API key required for Whisper API engine")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name

        try:
            async with httpx.AsyncClient() as client:
                with open(tmp_path, "rb") as audio_file:
                    response = await client.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        files={"file": ("audio.wav", audio_file, "audio/wav")},
                        data={"model": "whisper-1", "language": "en"},
                        timeout=30.0,
                    )
                    response.raise_for_status()
                    data = response.json()
                    return TranscriptionResult(text=data.get("text", ""))
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def is_available(self) -> bool:
        try:
            import os

            import httpx  # noqa: F401

            return bool(self._api_key or os.environ.get("OPENAI_API_KEY"))
        except ImportError:
            return False


class AppleSpeechEngine(TranscriptionEngine):
    """Native macOS speech recognition via Apple's Speech framework."""

    async def transcribe(self, wav_bytes: bytes) -> TranscriptionResult:
        """Transcribe using macOS Speech framework."""
        # This requires pyobjc-framework-Speech and runs synchronously
        import Foundation
        import Speech

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name

        try:
            url = Foundation.NSURL.fileURLWithPath_(tmp_path)
            recognizer = Speech.SFSpeechRecognizer.alloc().init()
            request = Speech.SFSpeechURLRecognitionRequest.alloc().initWithURL_(url)

            import asyncio

            loop = asyncio.get_event_loop()
            result_future = loop.create_future()

            def handler(result, error):
                if error:
                    loop.call_soon_threadsafe(
                        result_future.set_exception,
                        RuntimeError(f"Speech recognition error: {error}"),
                    )
                elif result and result.isFinal():
                    text = result.bestTranscription().formattedString()
                    loop.call_soon_threadsafe(
                        result_future.set_result,
                        TranscriptionResult(text=text),
                    )

            recognizer.recognitionTaskWithRequest_resultHandler_(request, handler)
            return await result_future
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def is_available(self) -> bool:
        try:
            import Speech  # noqa: F401

            return True
        except ImportError:
            return False


def create_engine(
    engine_type: Literal["whisper_local", "whisper_api", "apple_speech"] = "whisper_local",
    model_size: str = "base.en",
    api_key: str | None = None,
) -> TranscriptionEngine:
    """Factory function to create the appropriate transcription engine."""
    engines = {
        "whisper_local": lambda: WhisperLocalEngine(model_size=model_size),
        "whisper_api": lambda: WhisperAPIEngine(api_key=api_key),
        "apple_speech": lambda: AppleSpeechEngine(),
    }

    engine = engines[engine_type]()
    if not engine.is_available():
        logger.warning("Requested engine '%s' is not available, falling back...", engine_type)
        # Try fallback order
        for fallback_type in ["whisper_local", "apple_speech", "whisper_api"]:
            if fallback_type != engine_type:
                fallback = engines[fallback_type]()
                if fallback.is_available():
                    logger.info("Using fallback engine: %s", fallback_type)
                    return fallback

        raise RuntimeError(
            "No transcription engine available. Install faster-whisper: pip install faster-whisper"
        )

    return engine
