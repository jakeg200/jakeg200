"""Every model call in Atrium goes through here.

Three reasons it is one file:

1. **Fixture replay.** Every eval in `evals/` must run offline and deterministically (SPEC.md
   §10). Set ``ATRIUM_LLM=replay`` and calls are served from `evals/fixtures/llm/` keyed by a hash
   of the request. A missing fixture is an error, never a live call — a blocking eval that quietly
   reaches the network is not a blocking eval.
2. **Structured outputs.** Callers ask for a Pydantic model and get one, or get an exception. No
   downstream code parses model prose.
3. **One throat to choke for retries, timeouts, and cost.**

Modes, via ``ATRIUM_LLM``: ``replay`` (default when no API key), ``record`` (live + write
fixtures), ``live``.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "evals" / "fixtures" / "llm"

DEFAULT_MODEL = "claude-opus-5"
#: Recognition accuracy is M1's acceptance gate (>92% structural on real handwriting), so the
#: vision path does not get a cheaper model until that number says it can afford one.
VISION_MODEL = "claude-opus-5"


class LLMError(RuntimeError):
    pass


class FixtureMissing(LLMError):
    def __init__(self, key: str, path: Path) -> None:
        super().__init__(
            f"no fixture {key} at {path}. Re-record with ATRIUM_LLM=record, or the eval is "
            f"asserting against a call it has never seen."
        )
        self.key = key


def mode() -> str:
    explicit = os.environ.get("ATRIUM_LLM")
    if explicit:
        return explicit
    return "live" if os.environ.get("ANTHROPIC_API_KEY") else "replay"


def _key(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


class LLM:
    def __init__(self, model: str = DEFAULT_MODEL, max_retries: int = 3) -> None:
        self.model = model
        self.max_retries = max_retries

    def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        images: list[bytes] | None = None,
        max_tokens: int = 1024,
    ) -> T:
        # No `temperature`: it is removed on current models and returns a 400. Determinism comes
        # from the fixture-replay mode below, which is what the evals actually depend on.
        request = {
            "model": self.model,
            "system": system,
            "prompt": prompt,
            "schema": schema.__name__,
            "images": [hashlib.sha256(i).hexdigest()[:16] for i in (images or [])],
            "max_tokens": max_tokens,
        }
        key = _key(request)
        current = mode()

        if current == "replay":
            return self._replay(key, schema)

        raw = self._live(system, prompt, schema, images, max_tokens)
        if current == "record":
            FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
            (FIXTURE_DIR / f"{key}.json").write_text(
                json.dumps({"request": request, "response": raw}, indent=2), encoding="utf-8"
            )
        return self._parse(raw, schema)

    def _replay(self, key: str, schema: type[T]) -> T:
        path = FIXTURE_DIR / f"{key}.json"
        if not path.exists():
            raise FixtureMissing(key, path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return self._parse(data["response"], schema)

    def _parse(self, raw: Any, schema: type[T]) -> T:
        try:
            return schema.model_validate(raw)
        except ValidationError as exc:
            raise LLMError(f"model output did not match {schema.__name__}: {exc}") from exc

    def _live(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        images: list[bytes] | None,
        max_tokens: int,
    ) -> Any:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise LLMError("anthropic SDK not installed; pip install atrium[runtime]") from exc

        import base64

        client = anthropic.Anthropic(max_retries=self.max_retries)
        content: list[dict[str, Any]] = []
        for img in images or []:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(img).decode(),
                    },
                }
            )
        content.append({"type": "text", "text": prompt})

        # `messages.parse` with a Pydantic `output_format` is the current structured-output path:
        # the response is schema-validated server-side and comes back as an instance. The older
        # trick of forcing a single tool with `tool_choice` still works but buys nothing here.
        message = client.messages.parse(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_format=schema,
        )
        if message.stop_reason == "refusal":
            raise LLMError("model declined the request")
        if message.parsed_output is None:
            raise LLMError("model returned no structured output")
        return message.parsed_output.model_dump(mode="json")
