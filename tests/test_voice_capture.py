"""Tests for voice capture module (unit tests, no actual microphone)."""

import numpy as np

from prompt_pulse.voice.capture import SAMPLE_RATE, CaptureState, VoiceCapture


def test_initial_state():
    vc = VoiceCapture()
    assert vc.state == CaptureState.IDLE


def test_wav_conversion():
    vc = VoiceCapture()
    # Generate 1 second of silence
    audio = np.zeros(SAMPLE_RATE, dtype=np.int16)
    wav_bytes = vc._to_wav(audio)
    assert wav_bytes[:4] == b"RIFF"
    assert len(wav_bytes) > SAMPLE_RATE * 2  # 16-bit = 2 bytes per sample


def test_cancel():
    vc = VoiceCapture()
    vc.cancel()  # Should not raise even when not listening
    assert vc.state == CaptureState.IDLE
