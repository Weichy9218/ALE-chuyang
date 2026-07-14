"""Secret handling shared by the executors and their entry points.

API keys (OPENROUTER_API_KEY, ANTHROPIC_API_KEY, ...) must NEVER be
serialized into ``_spec.json`` — that file is gathered back to the host
into ``.logs/.../origin_log/<agent>/_spec.json`` and would persist
plaintext keys on host disk (committable / shareable).

Instead the framework writes the env into a sibling ``_secrets.json``
that the in-sandbox / in-container entry reads ONCE, injects into the
process environment, then deletes immediately. The gather step also
excludes this filename by name as defense-in-depth, so even a racing
or failed delete cannot leak it to host logs.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

# Basename of the transient secrets sidecar. Lives next to ``_spec.json``
# in the deployer work_dir; read-once, then deleted by the entry.
SECRETS_FILE = "_secrets.json"

# Control files that carry secrets and must never reach host logs. The
# gather paths exclude these by basename as a belt-and-suspenders guard.
SECRET_GATHER_EXCLUDES = frozenset({SECRETS_FILE, "_env"})

# Config-field names (exact, lowercased) that carry a secret VALUE and must be
# stripped out of ``_spec.json``'s ``config_kwargs`` (that file is gathered to
# host logs). The plaintext instead rides the read-once ``_secrets.json``
# sidecar under CFG_SECRET_PREFIX and is re-attached to the reconstructed
# config by the entry (split_config_secrets / apply_config_secrets).
#
# Match is EXACT, not substring, on purpose: ``api_key_env`` holds a VAR NAME
# (e.g. "OPENAI_API_KEY"), not a secret — the deployer's ``_resolve_api_key``
# reads that var — so it must NOT be captured here.
SECRET_CONFIG_FIELDS = frozenset(
    {
        "api_key",
        "apikey",
        "openai_api_key",
        "anthropic_api_key",
        "openrouter_api_key",
        "brave_api_key",
        "gemini_api_key",
        "google_api_key",
        "auth_token",
        "token",
        "password",
        "secret",
    }
)

# Prefix under which stripped config secrets ride the _secrets.json sidecar.
CFG_SECRET_PREFIX = "__ale_cfg_secret__"


def is_secret_field(name: str) -> bool:
    """True if a config field name holds a secret value (exact-match)."""
    return name.lower() in SECRET_CONFIG_FIELDS


def split_config_secrets(kwargs: dict) -> tuple[dict, dict]:
    """Split serialized config kwargs into (keyless_kwargs, sidecar_secrets).

    ``keyless_kwargs`` keeps every field but blanks secret-valued ones to
    ``None`` so it is safe to persist into ``_spec.json`` (gathered to host
    logs) and still reconstructs the dataclass (the field stays present even
    when it has no default). ``sidecar_secrets`` maps
    ``CFG_SECRET_PREFIX + field -> value`` for each blanked field that held a
    non-empty string, to be merged into the read-once ``_secrets.json`` sidecar
    and re-attached by :func:`apply_config_secrets` in the entry.
    """
    keyless: dict = {}
    secrets: dict = {}
    for k, v in kwargs.items():
        if is_secret_field(k):
            keyless[k] = None
            if isinstance(v, str) and v:
                secrets[CFG_SECRET_PREFIX + k] = v
        else:
            keyless[k] = v
    return keyless, secrets


def apply_config_secrets(cfg, env: dict) -> None:
    """Re-attach sidecar-carried config secrets onto a reconstructed config."""
    for k, v in (env or {}).items():
        if k.startswith(CFG_SECRET_PREFIX):
            setattr(cfg, k[len(CFG_SECRET_PREFIX):], v)


def strip_cfg_secrets(env: dict) -> dict:
    """Drop CFG_SECRET_PREFIX entries from ``env``.

    Those carry config secrets meant only for the reconstructed config object;
    they must not be injected into ``os.environ`` where the agent subprocess
    could read them.
    """
    return {
        k: v for k, v in (env or {}).items() if not k.startswith(CFG_SECRET_PREFIX)
    }


def write_secrets(work_dir: Path, env: dict[str, str]) -> Path:
    """Write ``env`` to ``<work_dir>/_secrets.json`` with 0600 perms.

    Returns the path written. An empty env still writes an empty object
    so the entry's read path is uniform.
    """
    path = Path(work_dir) / SECRETS_FILE
    path.write_text(json.dumps(dict(env or {})))
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass
    return path


def read_and_delete_secrets(work_dir: str | Path) -> dict[str, str]:
    """Read ``<work_dir>/_secrets.json``, then delete it immediately.

    Returns the env dict (empty if the file is absent). Deletion is
    best-effort but attempted before the dict is returned so the secret
    sidecar does not outlive the read even on the unhappy path.
    """
    path = Path(work_dir) / SECRETS_FILE
    try:
        raw = path.read_text()
    except (FileNotFoundError, OSError):
        return {}
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v) for k, v in (data or {}).items()}


def inject_env(env: dict[str, str]) -> None:
    """Inject ``env`` into ``os.environ`` (string-coerced)."""
    for k, v in (env or {}).items():
        os.environ[str(k)] = str(v)
