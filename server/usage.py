"""Rate limits and daily allowances, enforced on the server.

Allowances are counted in real units (replies, seconds of recorded audio,
characters spoken), not in guessed per-minute prices. Counters live in memory
and reset at midnight UTC or when the server restarts. A persistent store is
a Stage B task.
"""
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from .config import Settings

KINDS = ("replies", "audio_seconds", "tts_chars")


class LimitExceeded(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class UsageTracker:
    def __init__(self, settings: Settings):
        self.s = settings
        self._lock = threading.Lock()
        self._day = _today()
        self._client = defaultdict(lambda: defaultdict(float))
        self._global = defaultdict(float)
        self._requests = defaultdict(deque)

    def _limits(self, scope: str) -> dict:
        if scope == "client":
            return {"replies": self.s.client_daily_replies,
                    "audio_seconds": self.s.client_daily_audio_seconds,
                    "tts_chars": self.s.client_daily_tts_chars}
        return {"replies": self.s.global_daily_replies,
                "audio_seconds": self.s.global_daily_audio_seconds,
                "tts_chars": self.s.global_daily_tts_chars}

    def _roll_day(self) -> None:
        today = _today()
        if today != self._day:
            self._day = today
            self._client.clear()
            self._global.clear()

    def check_rate(self, client_id: str) -> None:
        """Sliding one-minute window of API requests per browser."""
        now = time.time()
        with self._lock:
            window = self._requests[client_id]
            while window and window[0] < now - 60:
                window.popleft()
            if len(window) >= self.s.rate_limit_per_minute:
                raise LimitExceeded("rate_limited", "You're sending requests quickly. Wait a few seconds, then try again.")
            window.append(now)

    def reserve(self, client_id: str, kind: str, amount: float) -> None:
        """Count usage up front, before calling the provider. Raises if it would exceed an allowance."""
        with self._lock:
            self._roll_day()
            if self._global[kind] + amount > self._limits("global")[kind]:
                raise LimitExceeded("global_budget", "Kinora has reached today's overall usage limit. Please try again tomorrow.")
            if self._client[client_id][kind] + amount > self._limits("client")[kind]:
                raise LimitExceeded("client_budget", _client_message(kind))
            self._client[client_id][kind] += amount
            self._global[kind] += amount

    def release(self, client_id: str, kind: str, amount: float) -> None:
        """Give back a reservation when the provider call failed before doing work."""
        with self._lock:
            self._client[client_id][kind] = max(0, self._client[client_id][kind] - amount)
            self._global[kind] = max(0, self._global[kind] - amount)

    def add_tokens(self, client_id: str, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            for scope in (self._client[client_id], self._global):
                scope["input_tokens"] += input_tokens
                scope["output_tokens"] += output_tokens

    def summary(self, client_id: str) -> dict:
        with self._lock:
            self._roll_day()
            limits = self._limits("client")
            used = {k: round(self._client[client_id][k], 1) for k in KINDS}
            fractions = {k: (used[k] / limits[k] if limits[k] else 1) for k in KINDS}
            warning = None
            if any(f >= 1 for f in fractions.values()):
                warning = "You've used today's allowance for part of Kinora. It resets at midnight UTC."
            elif any(f >= self.s.warn_at_fraction for f in fractions.values()):
                warning = "You're close to today's usage allowance. It resets at midnight UTC."
            return {"day": self._day, "used": used, "limits": limits, "warning": warning}

    def global_report(self) -> dict:
        """Totals plus an optional cost estimate from configured prices."""
        with self._lock:
            g = dict(self._global)
        s = self.s
        estimate = None
        if s.price_input_per_million or s.price_output_per_million:
            estimate = round(
                g.get("input_tokens", 0) / 1e6 * s.price_input_per_million
                + g.get("output_tokens", 0) / 1e6 * s.price_output_per_million
                + g.get("audio_seconds", 0) / 60 * s.price_transcribe_per_minute
                + g.get("tts_chars", 0) / 1e6 * s.price_tts_per_million_chars, 4)
        return {"day": self._day, "totals": g, "estimated_cost_usd": estimate}


def _client_message(kind: str) -> str:
    return {
        "replies": "You've reached today's message allowance. It resets at midnight UTC.",
        "audio_seconds": "You've reached today's voice recording allowance. You can keep chatting by text.",
        "tts_chars": "You've reached today's spoken-reply allowance. Replies will still appear as text.",
    }[kind]
