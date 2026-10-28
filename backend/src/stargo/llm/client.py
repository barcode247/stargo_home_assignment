"""Minimal OpenAI-compatible chat client (Groq, Gemini and Ollama all speak it).

Only stdlib networking, one configured endpoint, and logs that carry provider,
status and latency but never prompts, message bodies or keys.
"""

import json
import logging
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("stargo.llm")

PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai",
               "gemini-flash-lite-latest"),
    "ollama": ("http://localhost:11434/v1", "llama3.1:8b"),
}


class LlmError(Exception):
    """Any failure talking to the model. The message never includes prompt text."""


class LlmTimeout(LlmError, TimeoutError):
    pass


@dataclass(frozen=True)
class LlmSettings:
    provider: str
    base_url: str
    model: str
    api_key: str | None
    timeout_s: float
    min_interval_s: float = 0.0  # pause between calls, for free-tier rate limits

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


def load_dotenv(path: Path) -> None:
    """Tiny .env reader: KEY=VALUE lines, never overrides the real environment."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_settings(env: dict[str, str] | None = None) -> LlmSettings | None:
    """None means rules-only mode."""
    env = os.environ if env is None else env
    provider = env.get("LLM_PROVIDER", "").strip().lower()
    if provider in ("", "none", "rules"):
        return None
    if provider not in PROVIDERS:
        log.warning("unknown LLM_PROVIDER %r; running rules-only", provider)
        return None
    default_url, default_model = PROVIDERS[provider]
    key = env.get("LLM_API_KEY", "").strip() or None
    if key is None and provider != "ollama":
        log.warning("LLM_PROVIDER=%s but LLM_API_KEY is empty; running rules-only", provider)
        return None
    return LlmSettings(
        provider=provider,
        base_url=(env.get("LLM_BASE_URL") or default_url).rstrip("/"),
        model=env.get("LLM_MODEL") or default_model,
        api_key=key,
        timeout_s=float(env.get("LLM_TIMEOUT_SECONDS") or 20),
        min_interval_s=float(env.get("LLM_MIN_INTERVAL_SECONDS") or 0),
    )


class ChatClient:
    max_retries = 2
    # Circuit breaker: after this many failures in a row, stop calling the model for a while
    # and fail at once, so a dead or slow endpoint costs seconds, not a timeout per message.
    breaker_threshold = 3
    breaker_cooldown_s = 60.0

    def __init__(self, settings: LlmSettings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._failures = 0
        self._open_until = 0.0
        self._last_error = ""

    def complete_json(self, system: str, user: str) -> str:
        """Return the model's raw text. Callers validate it; nothing here trusts it."""
        if time.monotonic() < self._open_until:
            raise LlmError(f"model calls paused after repeated failures; last: {self._last_error}")
        try:
            content = self._call(system, user)
        except LlmError as exc:
            self._last_error = str(exc)
            self._failures += 1
            if self._failures >= self.breaker_threshold:
                self._open_until = time.monotonic() + self.breaker_cooldown_s
                log.warning("llm %s failed %d times in a row; pausing calls for %.0fs",
                            self.settings.label, self._failures, self.breaker_cooldown_s)
            raise
        self._failures = 0
        return content

    def _wait_for_slot(self) -> None:
        """Space calls at least min_interval_s apart; the wait is not counted as model time."""
        with self._lock:
            wait = self._last_call + self.settings.min_interval_s - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _call(self, system: str, user: str) -> str:
        payload = {
            "model": self.settings.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        request = urllib.request.Request(
            f"{self.settings.base_url}/chat/completions",
            data=json.dumps(payload).encode(), headers=headers, method="POST")

        self._wait_for_slot()
        deadline = time.monotonic() + self.settings.timeout_s
        for attempt in range(self.max_retries + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LlmTimeout("model call timed out")
            started = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=remaining) as response:
                    body = json.loads(response.read().decode("utf-8"))
                log.info("llm %s ok in %.1fs", self.settings.label, time.monotonic() - started)
                return self._content(body)
            except urllib.error.HTTPError as exc:
                log.warning("llm %s http %s", self.settings.label, exc.code)
                # Rate limited or briefly overloaded: worth a short retry inside the deadline.
                if exc.code in (429, 500, 502, 503) and attempt < self.max_retries:
                    time.sleep(min(2.0 * (attempt + 1), max(0.0, deadline - time.monotonic())))
                    continue
                raise LlmError(f"model endpoint returned HTTP {exc.code}") from None
            except TimeoutError:
                raise LlmTimeout("model call timed out") from None
            except urllib.error.URLError as exc:
                if isinstance(exc.reason, TimeoutError | socket.timeout):
                    raise LlmTimeout("model call timed out") from None
                log.warning("llm %s unreachable", self.settings.label)
                raise LlmError("model endpoint unreachable") from None
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise LlmError("model endpoint returned non-JSON") from None
        raise LlmError("model endpoint kept rate limiting")

    @staticmethod
    def _content(body: dict) -> str:
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LlmError("unexpected response shape") from None
        if not isinstance(content, str) or not content.strip():
            raise LlmError("empty model response")
        return content


def strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()
