"""Settings loaded from environment variables (.env in the project root).

Every limit here is enforced by the server. Change values in .env, not in code.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _str(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    force_demo: bool
    access_code: str   # empty = no access code required
    admin_token: str   # empty = admin usage report disabled

    chat_model: str
    chat_reasoning_effort: str
    transcribe_model: str
    tts_model: str
    request_timeout_s: float

    max_message_chars: int
    max_audio_bytes: int
    max_recording_seconds: int
    max_user_turns_per_session: int
    context_messages: int
    session_idle_minutes: int
    max_active_sessions: int
    rate_limit_per_minute: int

    client_daily_replies: int
    client_daily_audio_seconds: int
    client_daily_tts_chars: int
    global_daily_replies: int
    global_daily_audio_seconds: int
    global_daily_tts_chars: int
    warn_at_fraction: float

    # Optional cost estimates (USD). 0 means "not configured"; nothing is invented.
    price_input_per_million: float
    price_output_per_million: float
    price_transcribe_per_minute: float
    price_tts_per_million_chars: float

    @property
    def demo_mode(self) -> bool:
        return self.force_demo or not self.openai_api_key


def load_settings() -> Settings:
    return Settings(
        openai_api_key=_str("OPENAI_API_KEY", ""),
        force_demo=_str("KINORA_FORCE_DEMO", "0") in ("1", "true", "yes"),
        access_code=_str("KINORA_ACCESS_CODE", ""),
        admin_token=_str("KINORA_ADMIN_TOKEN", ""),
        chat_model=_str("KINORA_CHAT_MODEL", "gpt-6-luna"),
        chat_reasoning_effort=_str("KINORA_CHAT_REASONING_EFFORT", "none"),
        transcribe_model=_str("KINORA_TRANSCRIBE_MODEL", "gpt-transcribe"),
        tts_model=_str("KINORA_TTS_MODEL", "gpt-4o-mini-tts"),
        request_timeout_s=_float("KINORA_REQUEST_TIMEOUT_SECONDS", 30.0),
        max_message_chars=_int("KINORA_MAX_MESSAGE_CHARS", 2000),
        max_audio_bytes=_int("KINORA_MAX_AUDIO_BYTES", 5_000_000),
        max_recording_seconds=_int("KINORA_MAX_RECORDING_SECONDS", 60),
        max_user_turns_per_session=_int("KINORA_MAX_TURNS_PER_SESSION", 40),
        context_messages=_int("KINORA_CONTEXT_MESSAGES", 30),
        session_idle_minutes=_int("KINORA_SESSION_IDLE_MINUTES", 60),
        max_active_sessions=_int("KINORA_MAX_ACTIVE_SESSIONS", 200),
        rate_limit_per_minute=_int("KINORA_RATE_LIMIT_PER_MINUTE", 20),
        client_daily_replies=_int("KINORA_CLIENT_DAILY_REPLIES", 60),
        client_daily_audio_seconds=_int("KINORA_CLIENT_DAILY_AUDIO_SECONDS", 900),
        client_daily_tts_chars=_int("KINORA_CLIENT_DAILY_TTS_CHARS", 30000),
        global_daily_replies=_int("KINORA_GLOBAL_DAILY_REPLIES", 300),
        global_daily_audio_seconds=_int("KINORA_GLOBAL_DAILY_AUDIO_SECONDS", 3600),
        global_daily_tts_chars=_int("KINORA_GLOBAL_DAILY_TTS_CHARS", 150000),
        warn_at_fraction=_float("KINORA_WARN_AT_FRACTION", 0.8),
        price_input_per_million=_float("KINORA_PRICE_INPUT_PER_MILLION", 0),
        price_output_per_million=_float("KINORA_PRICE_OUTPUT_PER_MILLION", 0),
        price_transcribe_per_minute=_float("KINORA_PRICE_TRANSCRIBE_PER_MINUTE", 0),
        price_tts_per_million_chars=_float("KINORA_PRICE_TTS_PER_MILLION_CHARS", 0),
    )
