"""ArgusDeployer — runs the Argus multi-role harness as an ALE agent.

Argus (``argus-skill``) orchestrates four roles — Manager, Planner, Engineer,
Reviewer — each of which is one ``codex exec`` subprocess. It owns no model of
its own, so from ALE's side this is "the codex agent, driven by a supervisor
instead of a single turn".

Why the **sandbox** executor (and only that)
--------------------------------------------

``ale_claw`` is the one agent that runs on the framework host, because it
implements its own tool layer: every exec/filesystem call it makes is an RPC
into the eval VM. Argus cannot do that — its execution surface is the codex
CLI's *built-in* shell and file tools, which act on whatever machine codex runs
on. Host-side, the roles would read and write the harness box (including
staged task data) while the deliverable was supposed to land in the VM.

Running the deployer under :class:`SandboxExecutor` puts argus, codex, and
every role's shell inside the evaluation VM. The task's exact output paths are
then plain local paths, the host is unreachable by construction, and the only
thing still needing a bridge is the GUI — which the cua MCP server already
provides, wired the same way the codex agent wires it.

Layout inside the VM
--------------------

``work_dir`` (gathered to the host after the episode)::

    prompt.txt              the ALE instruction handed to Argus
    spec.json               launcher input
    argus_summary.json      launcher output (supervisor summary or traceback)
    argus_stdout.log        launcher + role stream logs
    argus_stderr.log
    argus_home/             ARGUS_SKILL_HOME for this episode
      projects/<id>/events.jsonl    the role-by-role event log
    project/                the roles' working directory
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, ClassVar

from ale_run.base_interface import (
    AgentRunResult,
    BaseAgentDeployer,
    TrajectoryBuilder,
)

from .config import ArgusConfig

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 2.0
_TERM_GRACE_S = 5.0

#: Session id (and therefore the ``argus_home/projects/<id>/`` folder name).
#: Fixed rather than random so :attr:`ArgusDeployer.hot_artifacts` can name the
#: event log, and so a gathered run tree is the same shape every time.
_SESSION_ID = "ale"


class _ConfigView:
    """The executor as the codex deployer expects to see it.

    :class:`~ale_run.agents.codex.deployer.CodexDeployer` reads its knobs off
    ``executor.config``. Handing it a view whose ``config`` is a
    :class:`CodexConfig` — and whose every other attribute is the real
    executor's — lets us reuse its install path verbatim instead of keeping a
    second copy of "provision the pinned codex fork and write config.toml".
    """

    def __init__(self, executor: Any, config: Any) -> None:
        self._executor = executor
        self.config = config

    def __getattr__(self, name: str) -> Any:
        return getattr(self._executor, name)


class ArgusDeployer(BaseAgentDeployer):
    """Deployer for the Argus 4-role harness. Sandbox (in-VM) only."""

    default_executor: ClassVar[str] = "sandbox"
    supported_executors: ClassVar[frozenset[str]] = frozenset({"sandbox"})
    hot_artifacts: ClassVar[tuple[str, ...]] = (
        "argus_stdout.log",
        "argus_stderr.log",
        f"argus_home/projects/{_SESSION_ID}/events.jsonl",
        # The raw per-role codex frames go to this sibling, not to events.jsonl
        # (``_io_log.py``: ``log_path.with_name("agent_io.jsonl")``). Without it
        # a SIGTERM'd episode keeps its orchestration markers but loses every
        # tool call.
        f"argus_home/projects/{_SESSION_ID}/agent_io.jsonl",
    )

    @property
    def version(self) -> str | None:
        """Installed ``argus-skill`` version, resolved after :meth:`install`."""
        return getattr(self, "_argus_version", None)

    # =========================================================================
    # install
    # =========================================================================

    async def install(self) -> None:
        cfg: ArgusConfig = self.config  # type: ignore[assignment]

        if cfg.runner_backend != "codex":
            raise RuntimeError(
                f"argus: runner_backend={cfg.runner_backend!r} is not provisioned "
                "by this deployer (only 'codex' is). Install that CLI in the "
                "image, or extend install()."
            )

        # 1. codex CLI (pinned fork) + node/npm + cua MCP bridge + config.toml.
        #    Delegated so there is one implementation of this, in the codex agent.
        from ale_run.agents.codex.deployer import CodexDeployer

        codex_cfg = cfg.codex_config()
        provisioner = CodexDeployer(_ConfigView(self.executor, codex_cfg))  # type: ignore[arg-type]
        await provisioner.install()
        self._codex_path = shutil.which("codex") or "codex"
        logger.info("argus: codex CLI ready at %s", self._codex_path)

        self._augment_codex_config(cfg)

        # 2. argus-skill itself.
        await self._pip_install_argus(cfg)

        # 3. Work dir skeleton. Created before launch so a crash in the first
        #    seconds still gathers a well-formed (empty) tree.
        wd = Path(self.executor.work_dir)
        for sub in ("", "argus_home", "project"):
            (wd / sub).mkdir(parents=True, exist_ok=True)

        logger.info(
            "argus: install ok (model=%s, argus=%s, work_dir=%s)",
            cfg.model, self._argus_version, wd,
        )

    @staticmethod
    def _augment_codex_config(cfg: ArgusConfig) -> None:
        """Add the context-budget keys the codex deployer's writer does not emit.

        Without a catalog, ``model_context_window`` is the only thing telling
        codex how much room the model has; with one, it still pins the budget if
        the pinned fork rejects the catalog's field set (its ``ModelInfo`` is
        older than the build the catalog was validated against). Both keys are
        top-level, so they are inserted ahead of the first ``[table]`` header —
        TOML would otherwise read them as members of that table.
        """
        extra = []
        if cfg.model_context_window > 0:
            extra.append(f"model_context_window = {cfg.model_context_window}")
        if cfg.model_auto_compact_token_limit > 0:
            extra.append(
                "model_auto_compact_token_limit = "
                f"{cfg.model_auto_compact_token_limit}"
            )
        if not extra:
            return

        config_path = Path(os.path.expanduser("~")) / ".codex" / "config.toml"
        try:
            lines = config_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise RuntimeError(
                f"argus: cannot read {config_path} written by the codex "
                f"provisioner: {exc}"
            ) from exc

        cut = next(
            (i for i, line in enumerate(lines) if line.lstrip().startswith("[")),
            len(lines),
        )
        merged = lines[:cut] + extra + lines[cut:]
        config_path.write_text("\n".join(merged) + "\n", encoding="utf-8")
        logger.info("argus: config.toml augmented with %s", ", ".join(extra))

    @classmethod
    def _resolve_argus_requirement(cls, cfg: ArgusConfig) -> str:
        """The pip requirement to install, defaulting to the vendored wheel.

        The wheel sits next to this module, so it travels into the sandbox with
        the ``ale_run`` source tree the executor already ships — the only route
        available, since the sandbox cannot read the harness host and the
        package is not on PyPI.
        """
        if cfg.argus_package:
            return cfg.argus_package
        vendor = Path(__file__).resolve().parent / "_vendor"
        wheels = sorted(vendor.glob("argus_skill-*.whl"))
        if not wheels:
            raise RuntimeError(
                f"argus: no vendored wheel under {vendor} and argus_package is "
                "empty. Build one with `python -m build --wheel` from the "
                "argus-skill source and drop it there, or set argus_package."
            )
        return str(wheels[-1])

    async def _pip_install_argus(self, cfg: ArgusConfig) -> None:
        """``pip install`` argus-skill into the sandbox interpreter."""
        requirement = self._resolve_argus_requirement(cfg)
        argv = [sys.executable, "-m", "pip", "install", "--quiet"]
        if cfg.argus_pip_index_url:
            argv += ["--index-url", cfg.argus_pip_index_url]
        argv.append(requirement)

        proc = await asyncio.to_thread(
            subprocess.run, argv, capture_output=True, text=True, timeout=900,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"argus: pip install {requirement!r} failed "
                f"(rc={proc.returncode}): {(proc.stderr or '')[:800]}"
            )

        probe = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c",
             "import argus_skill; print(argus_skill.__version__)"],
            capture_output=True, text=True, timeout=60,
        )
        if probe.returncode != 0:
            raise RuntimeError(
                "argus: argus_skill is not importable after install: "
                f"{(probe.stderr or '')[:800]}"
            )
        self._argus_version = (probe.stdout or "").strip()

        # The ale_last_exam vertical is what makes this an ALE agent rather than
        # a paper pipeline. A published wheel that predates it would run every
        # episode under the research stages, silently.
        vertical_probe = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c",
             "from argus_skill.verticals._base import load_vertical; "
             "m = load_vertical('ale_last_exam'); print(m.__name__)"],
            capture_output=True, text=True, timeout=60,
        )
        loaded = (vertical_probe.stdout or "").strip()
        if vertical_probe.returncode != 0 or "ale_last_exam" not in loaded:
            raise RuntimeError(
                "argus: the installed argus-skill has no 'ale_last_exam' vertical "
                f"(load_vertical resolved to {loaded or '<error>'}). Point "
                "argus_package at a build that ships it."
            )

    # =========================================================================
    # launch
    # =========================================================================

    async def launch(self, prompt: str) -> AgentRunResult:
        cfg: ArgusConfig = self.config  # type: ignore[assignment]
        wd = Path(self.executor.work_dir)
        wd.mkdir(parents=True, exist_ok=True)

        prompt_file = wd / "prompt.txt"
        spec_file = wd / "spec.json"
        summary_file = wd / "argus_summary.json"
        stdout_log = wd / "argus_stdout.log"
        stderr_log = wd / "argus_stderr.log"
        pid_file = wd / "argus.pid"

        for f in (summary_file, stdout_log, stderr_log, pid_file):
            if f.exists():
                try:
                    f.unlink()
                except OSError:
                    pass

        prompt_file.write_text(prompt, encoding="utf-8")
        spec_file.write_text(
            json.dumps(self._build_spec(cfg, wd), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        argv = [sys.executable, "-m", "ale_run.agents.argus._launcher", str(spec_file)]
        env = self._build_env(cfg)

        t0 = time.monotonic()
        with open(stdout_log, "wb") as out, open(stderr_log, "wb") as err:
            proc = await asyncio.to_thread(
                subprocess.Popen,
                argv,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                env=env,
                cwd=str(wd),
                start_new_session=hasattr(os, "setsid"),
            )
        pid_file.write_text(str(proc.pid), encoding="ascii")
        logger.info("argus: launcher spawned pid=%s", proc.pid)

        try:
            while proc.poll() is None:
                await asyncio.sleep(_POLL_INTERVAL_S)
        except asyncio.CancelledError:
            # Episode wall-clock expired. Reap the whole group — the launcher,
            # every role's codex process, and their stdio MCP servers.
            self._terminate_proc_group(proc, force=False)
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(proc.wait), timeout=_TERM_GRACE_S,
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._terminate_proc_group(proc, force=True)
            raise

        duration_s = time.monotonic() - t0
        exit_code = proc.returncode
        status = "completed" if exit_code == 0 else "failed"
        error = None if status == "completed" else self._diagnose(
            summary_file, stderr_log, exit_code,
        )
        return AgentRunResult(
            status=status,
            pid=proc.pid,
            exit_code=exit_code,
            transcript_path=str(
                wd / "argus_home" / "projects" / _SESSION_ID / "events.jsonl"
            ),
            stderr_path=str(stderr_log),
            duration_s=duration_s,
            error=error,
        )

    def _build_spec(self, cfg: ArgusConfig, wd: Path) -> dict[str, Any]:
        return {
            "work_dir": str(wd),
            "prompt_file": str(wd / "prompt.txt"),
            "summary_path": str(wd / "argus_summary.json"),
            "argus_home": str(wd / "argus_home"),
            "project_workdir": str(wd / "project"),
            "session_id": _SESSION_ID,
            "project_label": f"ale-{uuid.uuid4().hex[:8]}",
            "vertical": cfg.vertical,
            "manager_division": cfg.manager_division,
            "workflow_mode": "staged",
            "backend": cfg.runner_backend,
            "max_missions": cfg.max_missions,
            "global_daily_cap_usd": cfg.global_daily_cap_usd,
            "iterate": cfg.iterate,
            "iteration_max_cycles": cfg.iteration_max_cycles,
        }

    def _build_env(self, cfg: ArgusConfig) -> dict[str, str]:
        env = os.environ.copy()
        for key, value in (self.executor.env or {}).items():
            env[str(key)] = str(value)
        env.update(cfg.role_env())
        # The launcher is addressed as ``ale_run.agents.argus._launcher``. The
        # sandbox entry exports the shipped source root on PYTHONPATH for its
        # own process, but the child gets an explicit env, and the deployer's
        # own cwd is not necessarily that root — so derive it from the loaded
        # package rather than trusting either.
        # ``ale_run`` is a namespace package (no __init__.py), so __file__ is
        # None and __path__ is the authority.
        import ale_run

        existing = env.get("PYTHONPATH", "")
        known = existing.split(os.pathsep) if existing else []
        for entry in reversed(list(getattr(ale_run, "__path__", []))):
            root = str(Path(entry).resolve().parent)
            if root not in known:
                known.insert(0, root)
        env["PYTHONPATH"] = os.pathsep.join(p for p in known if p)
        return env

    @staticmethod
    def _terminate_proc_group(proc: subprocess.Popen, *, force: bool) -> None:
        """Signal the launcher and every process it spawned."""
        try:
            if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                import signal

                os.killpg(
                    os.getpgid(proc.pid),
                    signal.SIGKILL if force else signal.SIGTERM,
                )
            elif force:
                proc.kill()
            else:
                proc.terminate()
        except (ProcessLookupError, OSError):
            pass

    @staticmethod
    def _diagnose(summary_file: Path, stderr_log: Path, exit_code: int | None) -> str:
        """Best available one-line cause for a non-zero launcher exit."""
        try:
            summary = json.loads(summary_file.read_text(encoding="utf-8"))
            if isinstance(summary, dict) and summary.get("error"):
                return str(summary["error"])
        except (OSError, json.JSONDecodeError):
            pass
        try:
            tail = stderr_log.read_text(encoding="utf-8", errors="replace")
            lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]
            if lines:
                return lines[-1][:500]
        except OSError:
            pass
        return f"argus launcher exited with code {exit_code}"

    # =========================================================================
    # parse_artifacts
    # =========================================================================

    @classmethod
    def parse_artifacts(
        cls,
        *,
        work_dir: Path,
        config: Any,
        run_result: AgentRunResult,
        builder: TrajectoryBuilder,
    ) -> None:
        from .events_to_trajectory import build_steps

        build_steps(
            work_dir=Path(work_dir),
            session_id=_SESSION_ID,
            run_result=run_result,
            builder=builder,
        )
