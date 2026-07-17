"""Domain-notes prep pre-step (harness capability B).

Runs at the Phase 1 -> Phase 2 seam in ``lifecycle.run_one_unit``: AFTER the
task inputs are staged and setup runs, BEFORE the agent launches. It produces
GENERAL, REUSABLE, NON-ANSWER notes about the software/tools and domain
conventions a task family needs (how to drive the tool, formats/units, common
pitfalls, how to self-verify), writes them into the sandbox as ``PREP_NOTES.md``,
and appends a one-line pointer to the task description so the agent knows the
file is there. The point is to hand the agent operational background instead of
making it rediscover it, and to nudge it toward building its own check.

Non-leak guarantee is STRUCTURAL, not just prompt-based: at this point in the
lifecycle the sandbox holds only ``input/`` + ``software/``. ``reference/`` (the
answers) is staged in Phase 3, AFTER the agent (see ``lifecycle.stage_reference``),
so the prep model physically cannot read the answer key. The prompt additionally
forbids solving the task or emitting task-specific values, and the notes are
cached per (domain, task-family stem) and reused across every instance/variant of
the family — which only works if they stay general, so family-level reuse is
itself a guard against instance-specific drift.

Gated OFF by default: ``maybe_prepare_domain_notes`` is a no-op unless the
``ALE_DOMAIN_PREP`` env var is truthy, so a normal run is byte-identical to
before. Best-effort throughout: any failure logs + emits an event and lets the
run proceed unprepped.

Env knobs:
  ALE_DOMAIN_PREP            truthy -> enable the pre-step (default off)
  ALE_DOMAIN_PREP_CACHE_DIR  host dir for the notes cache (default ~/.cache/ale_domain_prep)
  ALE_DOMAIN_PREP_SEARCH     truthy -> allow a bounded Exa/Firecrawl lookup (default off)
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from ..environments.task_data import join, shell_q, task_subdir

logger = logging.getLogger(__name__)

_NOTES_FILENAME = "PREP_NOTES.md"

# Tunable hyperparameters. Each is a default overridable via the matching env var,
# so the user controls them from the launcher (settings.yaml -> env) without
# editing code. Two limits bound the notes and move together: _prep_max_tokens()
# caps how many tokens the model can GENERATE (the real limit), _max_notes_chars()
# is the post-hoc char cap. Notes enter the agent's context only when it reads
# PREP_NOTES.md (~3k tok of a 128k window), so this is not a context concern.
_DEFAULT_MAX_NOTES_CHARS = 12000
_DEFAULT_MAX_DIGEST_CHARS = 4000
_DEFAULT_PREP_MAX_TOKENS = 3000
# gpt-5 family models only accept temperature=1 (litellm raises otherwise); fixed.
_PREP_TEMPERATURE = 1.0


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _max_notes_chars() -> int:
    return _int_env("ALE_DOMAIN_PREP_MAX_NOTES_CHARS", _DEFAULT_MAX_NOTES_CHARS)


def _max_digest_chars() -> int:
    return _int_env("ALE_DOMAIN_PREP_MAX_DIGEST_CHARS", _DEFAULT_MAX_DIGEST_CHARS)


def _prep_max_tokens() -> int:
    return _int_env("ALE_DOMAIN_PREP_MAX_TOKENS", _DEFAULT_PREP_MAX_TOKENS)

# A single trailing variant/level/instance marker, stripped repeatedly to get the
# reusable family stem: e.g. bpmn_..._restructuring_l3 -> bpmn_..._restructuring,
# legal_ma_consistency_audit_01 -> legal_ma_consistency_audit,
# internal_employee_agent_instance_1 -> internal_employee_agent.
_STEM_SUFFIX_RE = re.compile(
    r"_(?:l\d+|v\d+|instance_\d+|case_\d+|part_\d+|\d+)$", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable, no sandbox / no model)
# ---------------------------------------------------------------------------


def _family_stem(task_name: str) -> str:
    """Strip trailing variant/level/instance markers to a reusable family stem."""
    s = task_name or ""
    while True:
        stripped = _STEM_SUFFIX_RE.sub("", s)
        if stripped == s:
            break
        s = stripped
    return s or (task_name or "")


def prep_cache_key(domain: str, task_name: str) -> str:
    """Cache key for the notes: ``<domain>/<family-stem>``.

    Deterministic (no model). Reused across every variant/instance/rerun of the
    same family, which is where the "compute once, reuse" win comes from.
    """
    return f"{(domain or 'unknown').strip('/')}/{_family_stem(task_name)}"


def _cache_file(cache_dir: str, key: str) -> Path:
    """Map a cache key to a flat host-side filename under ``cache_dir``."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", key).strip("_") or "unknown"
    return Path(cache_dir) / f"{safe}.md"


def load_cached_notes(cache_dir: str, key: str) -> Optional[str]:
    p = _cache_file(cache_dir, key)
    try:
        if p.is_file():
            text = p.read_text(encoding="utf-8").strip()
            return text or None
    except OSError as e:
        logger.debug("domain_prep cache read failed for %s: %s", key, e)
    return None


def save_cached_notes(cache_dir: str, key: str, notes: str) -> None:
    p = _cache_file(cache_dir, key)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(notes, encoding="utf-8")
    except OSError as e:
        logger.debug("domain_prep cache write failed for %s: %s", key, e)


def _sanitize_notes(text: str) -> str:
    """Trim and hard-cap the model's notes so injection stays bounded."""
    t = (text or "").strip()
    cap = _max_notes_chars()
    if len(t) > cap:
        t = t[:cap].rstrip() + "\n\n... [truncated]"
    return t


def _build_prep_messages(
    domain: str,
    family: str,
    task_description: str,
    input_digest: str,
    search_context: str = "",
) -> list[dict[str, str]]:
    """Construct the (system, user) messages for the prep model call."""
    system = (
        f"You are preparing REUSABLE background notes for an autonomous agent that "
        f"will attempt a task in the '{domain}' domain (task family '{family}'). Your "
        f"notes will be saved as a reference file in the agent's working directory and "
        f"REUSED across every instance of this family.\n\n"
        f"Write only GENERAL, REUSABLE operational knowledge that helps any instance of "
        f"this kind of task:\n"
        f"- how to drive the relevant software/tools/libraries involved;\n"
        f"- domain conventions, expected units, and file/format details;\n"
        f"- common pitfalls and how to avoid them;\n"
        f"- how the agent could build its OWN check or simulation from the inputs to "
        f"verify its output before finishing.\n\n"
        f"HARD CONSTRAINTS:\n"
        f"- Do NOT solve this task or produce any part of its expected output. These are "
        f"background method/tool notes, not an answer.\n"
        f"- Do NOT invent or state task-specific values, thresholds, ids, or results. If a "
        f"general fact is uncertain, omit it rather than guess.\n"
        f"- Because these notes are reused across the whole family, keep every statement "
        f"general enough to hold for sibling instances.\n"
        f"- Be concise and practical: short bullet points. Markdown."
    )
    user_parts = [
        f"TASK DESCRIPTION (public prompt the agent will receive):\n{task_description.strip()}",
        f"\nINPUT FILE LISTING AND SMALL SAMPLES (to identify software/formats in play — "
        f"NOT the answer):\n{input_digest.strip() or '(none available)'}",
    ]
    if search_context.strip():
        user_parts.append(
            f"\nEXTERNAL REFERENCE SNIPPETS (from web search on the tools/domain):\n"
            f"{search_context.strip()}"
        )
    user_parts.append(
        "\nWrite the reusable background notes now. Start with a one-line title."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def _cp_stdout(cp: subprocess.CompletedProcess) -> str:
    """Best-effort str view of a CompletedProcess stdout (str or bytes)."""
    out = getattr(cp, "stdout", "") or ""
    if isinstance(out, bytes):
        return out.decode("utf-8", errors="replace")
    return str(out)


# ---------------------------------------------------------------------------
# Async steps (need the sandbox / the model)
# ---------------------------------------------------------------------------


async def _gather_input_digest(sandbox: Any, base: str) -> str:
    """A bounded listing + small file heads of the staged input/ dir.

    Uses only ``run_command`` (read-only). Never raises: on any error it returns
    whatever it collected (possibly empty).
    """
    input_dir = join(sandbox, base, "input")
    files_txt = ""
    try:
        cp = await sandbox.run_command(
            f"find {shell_q(sandbox, input_dir)} -maxdepth 3 -type f 2>/dev/null | head -n 60",
            timeout=30,
        )
        files_txt = _cp_stdout(cp).strip()
    except Exception as e:  # noqa: BLE001 — digest is best-effort
        logger.debug("domain_prep digest listing failed: %s", e)

    heads: list[str] = []
    for path in [p for p in files_txt.splitlines() if p.strip()][:5]:
        try:
            cp = await sandbox.run_command(
                f"head -c 800 {shell_q(sandbox, path)} 2>/dev/null", timeout=20,
            )
            sample = _cp_stdout(cp).strip()
            if sample:
                heads.append(f"--- {path} ---\n{sample}")
        except Exception as e:  # noqa: BLE001
            logger.debug("domain_prep digest sample failed for %s: %s", path, e)

    digest = "FILES:\n" + (files_txt or "(none)")
    if heads:
        digest += "\n\nSAMPLES:\n" + "\n\n".join(heads)
    return digest[:_max_digest_chars()]


async def _default_llm_fn(model: str, messages: list[dict[str, str]]) -> str:
    """Call the same model the agent uses, via ale_claw's proven helper path.

    Lazy import so orchestration does not hard-depend on the ale_claw package at
    module load. ``purpose='compaction'`` selects a plain chat completion.
    """
    from ..agents.ale_claw.harness.model.helper_runtime import call_helper_model

    result = await call_helper_model(
        model,
        purpose="compaction",
        messages=messages,
        max_tokens=_prep_max_tokens(),
        temperature=_PREP_TEMPERATURE,
        timeout=180,
    )
    return result.text


async def _maybe_search(domain: str, family: str) -> str:
    """Optional bounded web lookup for tool/domain docs. OFF unless enabled.

    Degrades to "" on any error or when no key is present. Reuses the guarded
    Exa/Firecrawl backend (with its answer-leak denylist) from the ale_claw tools.
    """
    if not _truthy(os.environ.get("ALE_DOMAIN_PREP_SEARCH")):
        return ""
    exa = (os.environ.get("EXA_API_KEY") or "").strip()
    fire = (os.environ.get("Firecrawl_API_KEY") or "").strip()
    if not exa and not fire:
        return ""
    try:
        from ..agents.ale_claw.harness.tools.tools_web import _run_web_search

        query = f"{domain} {family.replace('_', ' ')} tools format conventions how to"
        payload = await _run_web_search(exa, fire, query, 4, None)
        results = payload.get("results") or []
        lines = [
            f"- {r.get('title', '')} ({r.get('url', '')}): {r.get('description', '')}"
            for r in results
            if r.get("url")
        ]
        return "\n".join(lines)[:2000]
    except Exception as e:  # noqa: BLE001 — search is optional enrichment
        logger.info("domain_prep search skipped: %s", e)
        return ""


async def _inject_notes(sandbox: Any, base: str, notes: str) -> str:
    """Write PREP_NOTES.md into the sandbox task dir; return its remote path."""
    remote = join(sandbox, base, _NOTES_FILENAME)
    await sandbox.write_file(remote, notes)
    return remote


def _description_pointer(remote_path: str) -> str:
    return (
        f"\n\nBackground: a reusable reference file has been placed at "
        f"`{remote_path}` with general notes on the tools, formats, and pitfalls for "
        f"this kind of task (background knowledge, not the answer). Consult it if useful."
    )


async def prepare_domain_notes(
    *,
    sandbox: Any,
    task_data: Any,
    model: str,
    task_description: str,
    cache_dir: str,
    llm_fn: Callable[[str, list[dict[str, str]]], Awaitable[str]] = _default_llm_fn,
) -> Optional[dict[str, Any]]:
    """Produce/reuse notes, inject them into the sandbox, and return metadata.

    Returns ``{"notes": str, "remote_path": str, "cache_key": str, "cached": bool,
    "pointer": str}`` on success, or ``None`` if there was nothing to do. Raises
    only on programmer error; transport/model failures propagate to the caller,
    which treats them best-effort.
    """
    domain = getattr(task_data, "domain_name", "") or "unknown"
    task_name = getattr(task_data, "task_name", "") or ""
    key = prep_cache_key(domain, task_name)
    family = _family_stem(task_name)

    notes = load_cached_notes(cache_dir, key)
    cached = notes is not None
    if not cached:
        base = task_subdir(sandbox, task_data)
        digest = await _gather_input_digest(sandbox, base)
        search_context = await _maybe_search(domain, family)
        messages = _build_prep_messages(
            domain, family, task_description, digest, search_context
        )
        raw = await llm_fn(model, messages)
        notes = _sanitize_notes(raw)
        if not notes:
            return None
        save_cached_notes(cache_dir, key, notes)

    base = task_subdir(sandbox, task_data)
    remote = await _inject_notes(sandbox, base, notes)
    return {
        "notes": notes,
        "remote_path": remote,
        "cache_key": key,
        "cached": cached,
        "pointer": _description_pointer(remote),
    }


# ---------------------------------------------------------------------------
# Lifecycle entry point
# ---------------------------------------------------------------------------


def _truthy(v: Optional[str]) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def _default_cache_dir() -> str:
    return os.environ.get("ALE_DOMAIN_PREP_CACHE_DIR") or os.path.expanduser(
        "~/.cache/ale_domain_prep"
    )


async def maybe_prepare_domain_notes(
    *, env: Any, config: Any, task_meta: dict[str, Any], writer: Any,
) -> None:
    """Gate + best-effort wrapper called from the lifecycle.

    No-op unless ``ALE_DOMAIN_PREP`` is truthy. On success mutates
    ``task_meta['description']`` in place (appends the notes pointer) so the agent
    prompt at launch includes it. Never raises: prep is enrichment, not a gate.
    """
    if not (_truthy(os.environ.get("ALE_DOMAIN_PREP"))
            or getattr(config, "domain_prep", False)):
        return
    task_data = task_meta.get("task_data")
    if task_data is None or not getattr(task_data, "requires_task_data", False):
        return
    try:
        result = await prepare_domain_notes(
            sandbox=env.sandbox,
            task_data=task_data,
            model=getattr(config, "model", ""),
            task_description=task_meta.get("description", "") or "",
            cache_dir=_default_cache_dir(),
        )
    except Exception as e:  # noqa: BLE001 — best-effort; run proceeds unprepped
        logger.warning("domain_prep failed (best-effort, skipping): %s", e)
        if writer is not None:
            writer.emit_event("domain_prep_failed", error=str(e)[:300])
        return

    if not result:
        if writer is not None:
            writer.emit_event("domain_prep_skipped", reason="empty_notes")
        return

    task_meta["description"] = (
        (task_meta.get("description", "") or "").rstrip() + result["pointer"]
    )
    if writer is not None:
        writer.emit_event(
            "domain_prep_done",
            cache_key=result["cache_key"],
            cached=result["cached"],
            remote_path=result["remote_path"],
            notes_chars=len(result["notes"]),
        )
    logger.info(
        "domain_prep: %s notes for %s (%d chars) -> %s",
        "cached" if result["cached"] else "fresh",
        result["cache_key"], len(result["notes"]), result["remote_path"],
    )
