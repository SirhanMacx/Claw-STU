"""AppConfig and TaskRoute — the provider-layer configuration contract.

AppConfig is loaded from (in priority order):
  1. Environment variables
  2. ~/.claw-stu/secrets.json (0600 on POSIX; WARN on Windows)
  3. Defaults defined in this module

See docs/superpowers/specs/2026-04-11-claw-stu-providers-memory-proactive-design.md
§4.2.4 and §4.2.5 for the authoritative default routing table.

Tasks 6-8 add the env/file loader (`load_config`) and the data
directory bootstrap (`ensure_data_dir`). This module currently
ships only the data model and the default-routing helper.
"""
from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from clawstu.orchestrator.task_kinds import TaskKind

logger = logging.getLogger(__name__)


class TaskRoute(BaseModel):
    """One (provider, model) assignment for a TaskKind.

    Kept as a named pydantic model so the config file reads cleanly:
    {TaskKind: {provider: ..., model: ..., max_tokens: ..., temperature: ...}}
    rather than opaque tuples.
    """

    model_config = ConfigDict(frozen=True)

    provider: str  # "ollama" | "anthropic" | "openai" | "openrouter" | "echo"
    model: str     # provider-specific model id
    max_tokens: int = 1024
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


def _default_task_routing() -> dict[TaskKind, TaskRoute]:
    """The shipped defaults per design spec §4.2.4.

    The reader-friendly version of this table:

    - SOCRATIC_DIALOGUE   -> ollama / llama3.2         (short, local, free)
    - BLOCK_GENERATION    -> openrouter / glm-4.5-air  (prose quality)
    - CHECK_GENERATION    -> openrouter / glm-4.5-air  (structured JSON)
    - RUBRIC_EVALUATION   -> anthropic / haiku-4-5     (accuracy-critical)
    - PATHWAY_PLANNING    -> openrouter / glm-4.5-air  (small JSON)
    - CONTENT_CLASSIFY    -> ollama / llama3.2         (safety: never network)
    - DREAM_CONSOLIDATION -> openrouter / glm-4.5-air  (batch overnight)
    """
    return {
        TaskKind.SOCRATIC_DIALOGUE: TaskRoute(
            provider="ollama", model="llama3.2",
        ),
        TaskKind.BLOCK_GENERATION: TaskRoute(
            provider="openrouter", model="z-ai/glm-4.5-air",
        ),
        TaskKind.CHECK_GENERATION: TaskRoute(
            provider="openrouter", model="z-ai/glm-4.5-air",
        ),
        TaskKind.RUBRIC_EVALUATION: TaskRoute(
            provider="anthropic", model="claude-haiku-4-5",
        ),
        TaskKind.PATHWAY_PLANNING: TaskRoute(
            provider="openrouter", model="z-ai/glm-4.5-air",
        ),
        TaskKind.CONTENT_CLASSIFY: TaskRoute(
            provider="ollama", model="llama3.2",
        ),
        TaskKind.DREAM_CONSOLIDATION: TaskRoute(
            provider="openrouter", model="z-ai/glm-4.5-air",
        ),
    }


class AppConfig(BaseModel):
    """The Claw-STU runtime configuration.

    Loaded via `load_config()` — see Tasks 6-8. Validation is strict:
    missing provider API keys are fine (falls through the chain),
    but an unknown provider name in `fallback_chain` or `task_routing`
    is a hard error raised by the router at construction time (Phase 2).
    """

    # `extra="forbid"` turns a typo in secrets.json or a CLAW_STU_* env
    # var into a loud pydantic ValidationError at load_config time,
    # instead of pydantic's default behavior (silently ignore unknown
    # keys) which would leave the user debugging a typo for an hour.
    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    data_dir: Path = Field(
        default_factory=lambda: Path.home() / ".claw-stu",
        description="Root directory for secrets, brain, SQLite DB, cached models.",
    )
    primary_provider: str = "ollama"
    fallback_chain: tuple[str, ...] = (
        "ollama",
        "openai",
        "anthropic",
        "openrouter",
    )
    task_routing: dict[TaskKind, TaskRoute] = Field(
        default_factory=_default_task_routing,
    )
    # Provider connection settings.
    ollama_base_url: str = "http://localhost:11434"
    ollama_api_key: str | None = None
    anthropic_api_key: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    google_api_key: str | None = None
    google_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    # Session-layer settings.
    session_cache_size: int = 1024


def load_config() -> AppConfig:
    """Load configuration from env > file > defaults (priority order).

    1. Start with defaults from AppConfig's field defaults.
    2. Overlay values from ~/.claw-stu/secrets.json if it exists.
    3. Overlay env var values (highest priority).
    4. Construct AppConfig and return.

    Rationale for env-over-file: a developer setting ANTHROPIC_API_KEY
    in their shell should always win over whatever is in the file,
    even if they forget to clear it. File-over-env would produce
    surprising results.

    Env var names:
      CLAW_STU_DATA_DIR            -> data_dir
      OLLAMA_BASE_URL              -> ollama_base_url
      OLLAMA_API_KEY               -> ollama_api_key
      ANTHROPIC_API_KEY            -> anthropic_api_key
      ANTHROPIC_BASE_URL           -> anthropic_base_url
      OPENAI_API_KEY               -> openai_api_key
      OPENAI_BASE_URL              -> openai_base_url
      OPENROUTER_API_KEY           -> openrouter_api_key
      OPENROUTER_BASE_URL          -> openrouter_base_url
      STU_PRIMARY_PROVIDER         -> primary_provider
    """
    overrides: dict[str, object] = {}
    _apply_file_overrides(overrides)
    _apply_env_overrides(overrides)
    # `model_validate` accepts dict[str, Any] and keeps pydantic's own field
    # validation without forcing mypy --strict to reconcile a `**dict[str,
    # object]` spread against the per-field signature of BaseModel.__init__.
    return AppConfig.model_validate(overrides)


def _apply_file_overrides(overrides: dict[str, object]) -> None:
    """Mutate `overrides` with values from ~/.claw-stu/secrets.json.

    CLAW_STU_DATA_DIR is consulted here (not just in `_apply_env_overrides`)
    so test suites and relocated installs can redirect the file lookup
    without clobbering the final `data_dir` field. If the file does not
    exist, that is fine — fresh installs and `STU_*_API_KEY`-only setups
    never need it. A malformed JSON body raises ValueError with the path
    embedded so the operator can fix it in place.
    """
    data_dir_env = os.environ.get("CLAW_STU_DATA_DIR")
    data_dir = Path(data_dir_env) if data_dir_env else Path.home() / ".claw-stu"
    secrets_path = data_dir / "secrets.json"
    if not secrets_path.exists():
        logger.debug("no secrets.json at %s", secrets_path)
        return
    _check_secrets_permissions(secrets_path)
    try:
        payload = json.loads(secrets_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"secrets.json at {secrets_path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(
            f"secrets.json at {secrets_path} must be a JSON object, "
            f"got {type(payload).__name__}"
        )
    for key, value in payload.items():
        overrides[key] = value


def _check_secrets_permissions(secrets_path: Path) -> None:
    """WARN if secrets.json is not 0600 on POSIX. No-op on Windows.

    A hard fail would lock users out. A WARN gives them a chance to fix
    the permissions without downtime.
    """
    if os.name == "nt":
        logger.debug(
            "Windows detected; skipping POSIX permission check on %s. "
            "Treat ~/.claw-stu/ as sensitive and protect it via NTFS ACLs "
            "or a user-only profile location.",
            secrets_path,
        )
        return
    try:
        mode = secrets_path.stat().st_mode
    except OSError as exc:
        logger.warning("could not stat %s: %s", secrets_path, exc)
        return
    file_mode = stat.S_IMODE(mode)
    if file_mode != 0o600:
        logger.warning(
            "secrets.json at %s has permissions %o; "
            "recommended is 0600 (run `chmod 600 %s`)",
            secrets_path,
            file_mode,
            secrets_path,
        )


def _apply_env_overrides(overrides: dict[str, object]) -> None:
    """Mutate `overrides` with any env-var-specified field values.

    Empty-string env vars are preserved (e.g. `ANTHROPIC_API_KEY=""` sets
    the field to `""`) because explicit emptiness is a valid operator
    signal. `CLAW_STU_DATA_DIR` is the one exception: an empty string
    would collapse to `Path(".")` which is nonsensical, so a truthy
    guard is used for that field only.
    """
    env_map: dict[str, str] = {
        "OLLAMA_BASE_URL": "ollama_base_url",
        "OLLAMA_API_KEY": "ollama_api_key",
        "ANTHROPIC_API_KEY": "anthropic_api_key",
        "ANTHROPIC_BASE_URL": "anthropic_base_url",
        "OPENAI_API_KEY": "openai_api_key",
        "OPENAI_BASE_URL": "openai_base_url",
        "OPENROUTER_API_KEY": "openrouter_api_key",
        "OPENROUTER_BASE_URL": "openrouter_base_url",
        "GOOGLE_API_KEY": "google_api_key",
        "GOOGLE_BASE_URL": "google_base_url",
        "STU_PRIMARY_PROVIDER": "primary_provider",
    }
    for env_name, field_name in env_map.items():
        value = os.environ.get(env_name)
        if value is not None:
            overrides[field_name] = value

    data_dir = os.environ.get("CLAW_STU_DATA_DIR")
    if data_dir:
        overrides["data_dir"] = Path(data_dir)


def ensure_data_dir(cfg: AppConfig) -> None:
    """Create the data directory if it does not exist. 0700 on POSIX.

    Idempotent: second call is a no-op. Never silently overrides an
    existing directory's permissions — we only set the mode when we
    create the directory ourselves.
    """
    if cfg.data_dir.exists():
        return
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            cfg.data_dir.chmod(0o700)
        except OSError as exc:
            logger.warning("could not chmod %s to 0700: %s", cfg.data_dir, exc)
