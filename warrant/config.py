"""Runtime configuration.

Defaults are chosen so that a fresh clone runs the eval harness offline and
deterministically with no API key and no database server.
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LLMMode = Literal["live", "replay", "off"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WARRANT_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./warrant.db"

    # LLM wrapper. "replay" reads recorded fixtures and falls back to the deterministic
    # heuristic pipeline on a miss; "off" never touches the network at all; "live" calls
    # the API and (when record_fixtures is set) writes what comes back.
    llm_mode: LLMMode = "replay"
    llm_model: str = "claude-sonnet-4-6"
    llm_max_retries: int = 3
    llm_timeout_s: float = 30.0
    record_fixtures: bool = False
    fixture_dir: str = "evals/fixtures"

    # Verifier ladder.
    symbolic_timeout_s: float = 4.0
    judge_min_confidence: float = 0.85
    lean_enabled: bool = False
    lean_timeout_s: float = 20.0
    lean_image: str = "warrant/lean:latest"

    # Capability record. The record is learner-held and warrant-signed: warrant is the
    # verifier, not the awarding body. See SPEC section 13.
    record_issuer: str = "warrant"
    signing_key_hex: str | None = None
    secure_threshold: int = 3
    secure_min_distinct_tasks: int = 2
    secure_spacing_days: int = 7
    decay_days: int = 90


settings = Settings()
