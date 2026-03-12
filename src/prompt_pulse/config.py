"""Configuration loader with Pydantic models and YAML support."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

CONFIG_DIR = Path.home() / ".prompt-pulse"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
DEFAULT_CONFIG = Path(__file__).parent.parent.parent / "config.example.yaml"


class TerminalConfig(BaseModel):
    backend: Literal["auto", "shell_hook", "tmux", "iterm2", "generic"] = "auto"
    screen_buffer_lines: int = Field(default=100, ge=10, le=1000)
    poll_interval_ms: int = Field(default=2000, ge=500, le=10000)


class VoiceConfig(BaseModel):
    engine: Literal["whisper_local", "whisper_api", "apple_speech"] = "whisper_local"
    whisper_model: Literal["tiny.en", "base.en", "small.en"] = "base.en"
    silence_threshold_sec: float = Field(default=1.0, ge=0.3, le=5.0)
    max_duration_sec: float = Field(default=30.0, ge=5.0, le=120.0)
    vad_aggressiveness: int = Field(default=2, ge=0, le=3)


class LLMConfig(BaseModel):
    provider: Literal["ollama", "openai", "anthropic"] = "ollama"
    model: str = "llama3.2:8b"
    api_key: str | None = None
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=500, ge=100, le=4000)

    def resolve_api_key(self) -> str | None:
        """Resolve env var references like ${OPENAI_API_KEY}."""
        if self.api_key and self.api_key.startswith("${") and self.api_key.endswith("}"):
            env_var = self.api_key[2:-1]
            return os.environ.get(env_var)
        return self.api_key


class DeliveryConfig(BaseModel):
    method: Literal["clipboard", "iterm_paste", "api", "file"] = "clipboard"
    show_notification: bool = True
    notification_preview_chars: int = Field(default=100, ge=20, le=500)


class HotkeyConfig(BaseModel):
    activate: str = "ctrl+shift+p"
    context_only: str = "ctrl+shift+l"
    re_enhance: str = "ctrl+shift+r"
    cancel: str = "escape"


class AppConfig(BaseModel):
    terminal: TerminalConfig = TerminalConfig()
    voice: VoiceConfig = VoiceConfig()
    llm: LLMConfig = LLMConfig()
    delivery: DeliveryConfig = DeliveryConfig()
    hotkeys: HotkeyConfig = HotkeyConfig()


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load configuration from YAML file, falling back to defaults."""
    path = config_path or CONFIG_FILE

    if path.exists():
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        return AppConfig(**raw)

    # Fall back to example config if it exists
    if DEFAULT_CONFIG.exists():
        with open(DEFAULT_CONFIG) as f:
            raw = yaml.safe_load(f) or {}
        return AppConfig(**raw)

    return AppConfig()


def init_config_dir() -> Path:
    """Create the config directory and copy example config if needed."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists() and DEFAULT_CONFIG.exists():
        import shutil

        shutil.copy(DEFAULT_CONFIG, CONFIG_FILE)
    return CONFIG_DIR
