"""The single door to the model.

Three modes:

* ``live``   — call the API. With ``record_fixtures`` set, every response is written to
               disk so it can be replayed.
* ``replay`` — read a recorded fixture. On a miss, return nothing.
* ``off``    — never touch the network; always return nothing.

"Return nothing" is a first-class outcome, not an error. Every caller degrades to a
deterministic path when the model is unavailable, which is what lets `make eval` run
offline in CI and what stops an API outage from turning into wrong judgements about
people. A model that cannot be reached must never become a model that guesses.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from warrant.config import settings

log = logging.getLogger("warrant.llm")


_client: Any = None
_stats: dict[str, int] = {"live": 0, "replay_hit": 0, "replay_miss": 0, "error": 0}


def stats() -> dict[str, int]:
    return dict(_stats)


def reset_stats() -> None:
    for key in _stats:
        _stats[key] = 0


def _fingerprint(purpose: str, system: str, prompt: str, schema: type[BaseModel]) -> str:
    payload = json.dumps(
        {
            "purpose": purpose,
            "model": settings.llm_model,
            "system": system,
            "prompt": prompt,
            "schema": schema.model_json_schema(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def _fixture_path(purpose: str, fingerprint: str) -> Path:
    return Path(settings.fixture_dir) / purpose / f"{fingerprint}.json"


def _client_or_none() -> Any:
    global _client
    if _client is not None:
        return _client
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        from anthropic import Anthropic
    except ImportError:  # pragma: no cover
        return None
    _client = Anthropic(timeout=settings.llm_timeout_s)
    return _client


def _call_api(system: str, prompt: str, schema: type[BaseModel]) -> dict[str, Any] | None:
    client = _client_or_none()
    if client is None:
        return None

    tool = {
        "name": "respond",
        "description": f"Return a well-formed {schema.__name__}.",
        "input_schema": schema.model_json_schema(),
    }
    delay = 1.0
    for attempt in range(settings.llm_max_retries):
        try:
            message = client.messages.create(
                model=settings.llm_model,
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                tools=[tool],
                tool_choice={"type": "tool", "name": "respond"},
            )
            for block in message.content:
                if getattr(block, "type", None) == "tool_use":
                    return dict(block.input)
            return None
        except Exception as exc:
            _stats["error"] += 1
            log.warning("llm call failed (attempt %d): %s", attempt + 1, exc)
            if attempt == settings.llm_max_retries - 1:
                return None
            time.sleep(delay)
            delay *= 2
    return None


def complete[T: BaseModel](
    *,
    purpose: str,
    system: str,
    prompt: str,
    schema: type[T],
) -> T | None:
    """Ask the model for a structured answer, or return None if we cannot get one."""
    fingerprint = _fingerprint(purpose, system, prompt, schema)
    path = _fixture_path(purpose, fingerprint)

    if settings.llm_mode == "off":
        return None

    if settings.llm_mode == "replay":
        if path.exists():
            _stats["replay_hit"] += 1
            try:
                return schema.model_validate_json(path.read_text())
            except ValidationError:
                log.warning("stale fixture at %s", path)
                return None
        _stats["replay_miss"] += 1
        return None

    raw = _call_api(system, prompt, schema)
    if raw is None:
        return None
    try:
        parsed = schema.model_validate(raw)
    except ValidationError as exc:
        log.warning("model returned a response that did not fit %s: %s", schema.__name__, exc)
        return None
    _stats["live"] += 1

    if settings.record_fixtures:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(parsed.model_dump_json(indent=2))
    return parsed


def available() -> bool:
    """True when a model answer is at least possible."""
    if settings.llm_mode == "off":
        return False
    if settings.llm_mode == "replay":
        return Path(settings.fixture_dir).exists()
    return _client_or_none() is not None
