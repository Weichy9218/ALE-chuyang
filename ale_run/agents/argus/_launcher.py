"""In-sandbox driver for one Argus episode.

Invoked by :class:`~ale_run.agents.argus.deployer.ArgusDeployer` as::

    python -m ale_run.agents.argus._launcher <spec.json>

**Why a separate process.** ``argus-skill``'s headless entry point
(``apps._runtime._invoke_supervisor`` → ``LifeSupervisor.run``) is synchronous
and blocks for the whole episode. A deployer that called it in-process could
not honour the framework's ``asyncio.wait_for`` cancellation on episode
timeout. Running it as a child means the deployer kills the whole process group
and reaps every codex subprocess with it.

**What it does.**

1. Opens an episode-private argus runtime under ``ARGUS_SKILL_HOME`` (inside
   the deployer's work_dir, so the framework gathers it with everything else).
2. Pins the vertical to ``ale_last_exam`` unless the config asked for a real
   Manager classification. The pin replaces only the Manager's *choice* — the
   commit path, stage plan, Planner handoff, and every downstream role run
   exactly as they would after a model-decided division.
3. Runs the full Manager → Planner → Engineer → Reviewer supervisor over the
   ALE instruction as a continuous objective, bounded by ``max_missions``.
4. Writes ``argus_summary.json`` next to the spec for the deployer to read.

Stdlib + argus-skill only. Nothing here imports ``ale_run`` beyond being
addressable as a module, so it runs under whatever interpreter pip-installed
argus-skill.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any


def _log(message: str) -> None:
    print(f"[argus-launcher] {message}", file=sys.stderr, flush=True)


def _seed_skills(skills_dir: Path) -> None:
    """Copy WS2 skills into the episode's skills dir before the supervisor runs.

    Off by default: only fires when ``ARGUS_SEED_SKILLS_DIR`` is set (any value).
    This is the skills lever's on/off switch for argus (the +skills arm sets the
    env via config.extra_env; the base arm leaves it unset). The seed tree mirrors
    argus's role layout (``engineer/<name>.md`` etc.); files are copied verbatim
    into ``ARGUS_SKILL_SKILLS_DIR`` so ``SkillStore.rglob('*.md')`` discovers them
    alongside the vertical seeds. We copy AFTER memory/vertical init so nothing
    clobbers them, and never overwrite an existing episode file.

    **Source resolution.** This launcher runs INSIDE the sandbox container (the
    argus root resolves under ``/home/user/.ale/...``), so a host path handed via
    the env var (e.g. ``/home/ubuntu/ale/.../seed_skills``) does not exist here.
    We therefore treat ``ARGUS_SEED_SKILLS_DIR`` purely as the on/off switch and
    resolve the actual tree package-relative to this module — ``seed_skills`` ships
    beside ``_launcher.py`` wherever the source root is mounted/exported into the
    sandbox, so ``__file__`` always points at the in-container copy. If the env
    value happens to name a real dir (host-mount case), we honour it instead.
    """
    src_raw = os.environ.get("ARGUS_SEED_SKILLS_DIR", "").strip()
    if not src_raw:
        return
    src = Path(src_raw)
    if not src.is_dir():
        pkg_seed = Path(__file__).resolve().parent / "seed_skills"
        if pkg_seed.is_dir():
            _log(
                f"ARGUS_SEED_SKILLS_DIR={src} not visible in sandbox; "
                f"falling back to package seed tree {pkg_seed}"
            )
            src = pkg_seed
        else:
            _log(
                f"ARGUS_SEED_SKILLS_DIR={src} is not a directory and package seed "
                f"tree {pkg_seed} is absent; no skills seeded"
            )
            return
    import shutil

    n = 0
    for md in sorted(src.rglob("*.md")):
        rel = md.relative_to(src)
        dst = skills_dir / rel
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(md, dst)
        n += 1
    _log(f"seeded {n} WS2 skill file(s) from {src} into {skills_dir}")


def _pin_vertical(vertical: str, execution_task: str, workflow_mode: str) -> None:
    """Make ``Manager.decide_vertical`` return a fixed committable decision.

    ``LifeSupervisor``'s continuous path always routes the objective through
    ``Manager.divide`` (there is no bypass parameter), and ``divide`` always
    calls ``decide_vertical`` — a model call whose answer is free to be
    ``research``, which would run the ALE episode as a paper pipeline. Binding
    the choice here keeps the Manager stage in the flow (it still commits the
    decision, plans stages, resets the stage pointer, and produces the
    Planner/Engineer handoff) while removing the one thing the harness already
    knows for certain.
    """
    from argus_skill.manager._core import Manager
    from argus_skill.manager.domain_author import VerticalDecision

    decision = VerticalDecision(
        choice="existing",
        vertical=vertical,
        workflow_mode=workflow_mode,
        execution_task=execution_task,
    )

    def _decide(self: Any, task: str, **_kwargs: Any) -> VerticalDecision:  # noqa: ANN401
        return decision

    Manager.decide_vertical = _decide  # type: ignore[method-assign]
    _log(f"vertical pinned to {vertical!r} (Manager classification skipped)")


def _seed_mission(mem: Any, instruction: str, spec: dict[str, Any]) -> None:  # noqa: ANN401
    """Enqueue the ALE instruction as the mission the Engineer actually receives.

    Left to itself, the supervisor's planning cycle fires only because the
    backlog is empty, and the item it authors is a templated "Goal Gate mission
    for the active staged project" whose objective tells the engineer to
    "re-read the original operator objective" — text that is nowhere in its
    prompt. Measured on a live episode: an 8.3k-char engineer prompt carrying
    the ALE role banner and not one word of the actual task (no output path, no
    method, no artifact name). Every task would score zero.

    Seeding the backlog puts the instruction verbatim into the mission objective,
    which is what the round prompt is built from. Manager still runs (it divides
    and commits the vertical before the drain begins); the Planner is simply not
    consulted, because it is only asked for work when the backlog runs dry and
    ``max_missions`` ends the episode before that happens.
    """
    from argus_skill.life.memory import BacklogItem

    item = BacklogItem.new(
        title="ALE task",
        objective=instruction,
        priority=0,
        tags=["ale", "ale_last_exam"],
        iterate=bool(spec.get("iterate", False)),
        iteration_max_cycles=int(spec.get("iteration_max_cycles", 1)),
    )
    item.original_objective = instruction
    mem.backlog.add(item)
    _log(
        f"seeded backlog item {item.id} with the ALE instruction "
        f"({len(instruction)} chars, iterate={item.iterate})"
    )


def run(spec: dict[str, Any]) -> dict[str, Any]:
    work_dir = Path(spec["work_dir"])
    argus_home = Path(spec["argus_home"])
    project_workdir = Path(spec["project_workdir"])
    session_id = str(spec["session_id"])
    instruction = Path(spec["prompt_file"]).read_text(encoding="utf-8")

    argus_home.mkdir(parents=True, exist_ok=True)
    project_workdir.mkdir(parents=True, exist_ok=True)

    # chdir, not just ARGUS_SKILL_WORKDIR. Several prompt-building layers
    # resolve the active vertical from ``Path.cwd()`` rather than from the
    # workdir they were handed, and a cwd with no ``research/PIPELINE_STATE.json``
    # silently falls back to the research (paper) vertical — observed in a live
    # run as an engineer prompt that argued with its own state file about
    # whether the stage was ``research`` or ``execute``.
    os.chdir(project_workdir)

    os.environ["ARGUS_SKILL_HOME"] = str(argus_home)
    os.environ["ARGUS_SKILL_WORKDIR"] = str(project_workdir)
    os.environ["ARGUS_SKILL_SESSION_ID"] = session_id
    os.environ.setdefault("ARGUS_SKILL_SKILLS_DIR", str(argus_home / "skills"))

    from argus_skill.life.memory import MemoryBundle

    mem = MemoryBundle.for_cwd(
        project_workdir,
        global_root=argus_home,
        fingerprint=session_id,
        label=spec.get("project_label") or session_id,
    )
    mem.init()
    project_root = Path(mem.project.root)
    _log(f"argus project root: {project_root}")

    # The engineer's cwd and the harness artifact root both get the vertical
    # marker: ``resolve_vertical`` is called against whichever root a given
    # layer happens to hold, and a missing marker degrades silently into the
    # research (paper) pipeline rather than failing.
    from argus_skill.skills.vertical_select import persist_vertical

    vertical = str(spec.get("vertical") or "ale_last_exam")
    for root in {project_root, project_workdir}:
        persist_vertical(root, vertical)

    if not spec.get("manager_division"):
        _pin_vertical(
            vertical,
            execution_task=instruction,
            workflow_mode=str(spec.get("workflow_mode") or "staged"),
        )

    _seed_mission(mem, instruction, spec)

    # WS2 skills lever (no-op unless ARGUS_SEED_SKILLS_DIR is set). Seeded here,
    # after memory + vertical init, so episode setup cannot clobber the files.
    _seed_skills(Path(os.environ["ARGUS_SKILL_SKILLS_DIR"]))

    from argus_skill.apps._runtime import _invoke_supervisor

    summary, thread_id = _invoke_supervisor(
        mem=mem,
        backend=str(spec.get("backend") or "codex"),
        once=bool(spec.get("max_missions", 1) <= 1),
        max_missions=int(spec.get("max_missions", 1)),
        global_daily_cap_usd=float(spec.get("global_daily_cap_usd", 1e6)),
        quiet=False,
        continuous=True,
        continuous_objective=instruction,
        # ALE is a bounded deliverable against a hidden reference, not an
        # open-ended campaign: no full-paper gate, no "invent more work".
        open_ended=False,
        allow_chat_fast_path=False,
    )
    return {
        "ok": True,
        "summary": summary,
        "thread_id": thread_id,
        "project_root": str(project_root),
        "events_path": str(project_root / "events.jsonl"),
        "work_dir": str(work_dir),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m ale_run.agents.argus._launcher <spec.json>",
              file=sys.stderr)
        return 2
    spec_path = Path(argv[1])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    summary_path = Path(spec["summary_path"])

    try:
        result = run(spec)
        rc = 0
    except BaseException as exc:  # noqa: BLE001 — every exit path must leave a summary
        result = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        rc = 1
        _log(result["traceback"])
    finally:
        try:
            summary_path.write_text(
                json.dumps(result, indent=2, default=str, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            _log(f"could not write summary to {summary_path}: {exc}")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
