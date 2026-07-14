"""PiDeployer — drives the ``@earendil-works/pi-coding-agent`` CLI.

Install via ``npm install -g`` (Node is baked into the ALE ubuntu image),
write a ``models.json`` describing the OpenAI-compatible provider, launch
``pi --mode json`` headlessly, and parse the NDJSON event stream into
trajectory steps.

Pi ships built-in ``read`` / ``bash`` / ``edit`` / ``write`` / ``grep`` /
``find`` / ``ls`` tools that operate directly on the container filesystem,
so — unlike the GUI-capable harnesses — this deployer needs no CUA MCP
bridge. It is Linux-only and runs in the ``sandbox`` executor (the deployer
process runs inside the task container, cwd = ``work_dir``).

Critical: pi blocks on stdin in ``--mode json``; the child is launched with
``stdin=DEVNULL`` so the turn actually starts.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, ClassVar

from ale_run.base_interface import (
    AgentRunResult,
    BaseAgentDeployer,
    ContentPart,
    Observation,
    StepMetrics,
    ToolCall,
    ToolResult,
    TrajectoryBuilder,
)

from .config import PiConfig

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 2.0
_TERM_GRACE_S = 3.0

_PROXY_ENV_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)

# stopReason 属于这些即认为是 LLM/网关层失败,不是模型正常收尾。
_ERROR_STOP_REASONS = frozenset({"error", "aborted"})


def _find_pi_shim(local_prefix: str) -> str | None:
    """Resolve the ``pi`` executable, preferring our ``~/.local`` install.

    The sandbox entry runs WITHOUT a login shell, so ``~/.local/bin`` may not
    be on PATH and ``shutil.which('pi')`` can miss a copy we just installed.
    Fall back to the exact npm shim path.
    """
    p = shutil.which("pi")
    if p and p.startswith(local_prefix):
        return p
    cand = os.path.join(local_prefix, "bin", "pi")
    if os.path.isfile(cand):
        return cand
    return p


def detect_llm_error_stop(transcript_path: Path) -> str | None:
    """返回最后一条 assistant 消息的错误信息;正常结束返回 None。

    pi --mode json 会把 LLM/网关层运行时错误(如 402 配额、网关 5xx 重试耗尽)
    吞成 exit code 0,于是纯看退出码会把故障误记为 completed、evaluate 在空工作区
    打假零分,--resume 还会永久跳过。这里倒序扫 transcript.jsonl 找最后一条
    role=assistant 的 message_end,若 stopReason 属于 {error, aborted} 就返回
    errorMessage,交给 launch() 改判 failed。

    只读最后一条 assistant message_end 的 stopReason;倒序扫,遇到第一条 assistant
    即判定,避免整文件解析。transcript 缺失/空按"无法判定"处理,返回 None(交给既有
    exit_code 逻辑),不误伤。切分与 parse_artifacts 一致只按真正的换行 \n 切,避免
    U+2028/U+2029/NEL 等 Unicode 行界把 JSON 事件从中间撕开。
    """
    if not transcript_path.exists():
        return None
    try:
        raw = transcript_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(raw.split("\n")):
        line = line.strip()
        if not line or '"message_end"' not in line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "message_end":
            continue
        msg = event.get("message") or {}
        if msg.get("role") != "assistant":
            continue
        stop = msg.get("stopReason")
        if stop in _ERROR_STOP_REASONS:
            return msg.get("errorMessage") or f"assistant stopReason={stop}"
        return None  # 最后一条 assistant 正常结束
    return None  # 没有 assistant 消息(空跑),交给 exit_code 逻辑


class PiDeployer(BaseAgentDeployer):
    """Stdlib-only deployer for the ``pi`` coding agent CLI."""

    default_executor: ClassVar[str] = "sandbox"
    supported_executors: ClassVar[frozenset[str]] = frozenset({"sandbox"})
    hot_artifacts: ClassVar[tuple[str, ...]] = ("transcript.jsonl", "stderr.log")

    @property
    def version(self) -> str | None:
        cfg: PiConfig = self.config  # type: ignore[assignment]
        return cfg.npm_package

    # =========================================================================
    # env helpers
    # =========================================================================

    def _base_env(self) -> dict[str, str]:
        """Process env for pi/npm children: os.environ + executor env, with
        the dead baked proxy optionally stripped so the container reaches the
        internet directly."""
        cfg: PiConfig = self.config  # type: ignore[assignment]
        env = os.environ.copy()
        for k, v in (self.executor.env or {}).items():
            env[str(k)] = str(v)
        if cfg.clear_proxy:
            for k in _PROXY_ENV_KEYS:
                env.pop(k, None)
            env["NO_PROXY"] = "*"
            env["no_proxy"] = "*"
        return env

    def _pi_config_dir(self) -> Path:
        home = os.path.expanduser("~")
        return Path(home) / ".pi" / "agent"

    def _resolve_api_key(self, cfg: PiConfig) -> str | None:
        if cfg.api_key:
            return cfg.api_key
        exec_env = dict(self.executor.env or {})
        return exec_env.get(cfg.api_key_env) or os.environ.get(cfg.api_key_env)

    # =========================================================================
    # install
    # =========================================================================

    async def install(self) -> None:
        cfg: PiConfig = self.config  # type: ignore[assignment]
        sandbox = self.executor.sandbox

        if not sandbox.is_linux:
            raise NotImplementedError("pi harness is Linux-only")

        home = os.path.expanduser("~")
        local_prefix = os.path.join(home, ".local")

        pi_path = _find_pi_shim(local_prefix)
        if not pi_path:
            logger.info("pi: 'pi' not on PATH, installing %s ...", cfg.npm_package)
            await self._install_cli(cfg.npm_package, local_prefix)
            pi_path = _find_pi_shim(local_prefix)
            if not pi_path:
                raise RuntimeError("PiDeployer: 'pi' still not found after npm install")
        else:
            logger.info("pi: reusing installed pi at %s", pi_path)
        self._pi_path = pi_path

        # Make sure the install dir is on PATH for the launch env.
        for bin_dir in (os.path.join(local_prefix, "bin"), local_prefix):
            if bin_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")

        # Probe version (best-effort).
        try:
            probe = await asyncio.to_thread(
                subprocess.run, [pi_path, "--version"],
                capture_output=True, text=True, timeout=30, env=self._base_env(),
            )
            logger.info("pi: CLI ok -- %s", (probe.stdout or probe.stderr or "").strip()[:80])
        except (subprocess.SubprocessError, OSError) as e:
            logger.warning("pi: --version probe failed: %s", e)

        # Work dir.
        Path(self.executor.work_dir).mkdir(parents=True, exist_ok=True)

        # Write models.json describing the OpenAI-compatible provider.
        api_key = self._resolve_api_key(cfg)
        if not api_key:
            raise RuntimeError(
                f"pi: no API key -- set config.api_key or executor env "
                f"{cfg.api_key_env!r}"
            )
        provider_cfg: dict[str, Any] = {
            "baseUrl": cfg.base_url,
            "api": cfg.api,
            "apiKey": api_key,
            "models": [
                {
                    "id": cfg.model,
                    "name": cfg.model,
                    "reasoning": bool(cfg.reasoning),
                    "contextWindow": int(cfg.context_window),
                    "maxTokens": int(cfg.max_tokens),
                }
            ],
        }
        if cfg.compat:
            provider_cfg["compat"] = dict(cfg.compat)

        models_doc = {"providers": {cfg.provider: provider_cfg}}
        cfg_dir = self._pi_config_dir()
        cfg_dir.mkdir(parents=True, exist_ok=True)
        models_path = cfg_dir / "models.json"
        models_path.write_text(json.dumps(models_doc, indent=2), encoding="utf-8")
        models_path.chmod(0o600)
        logger.info(
            "pi: models.json staged at %s (provider=%s model=%s base=%s)",
            models_path, cfg.provider, cfg.model, cfg.base_url,
        )

    async def _install_cli(self, package: str, prefix: str) -> None:
        npm = shutil.which("npm")
        if not npm:
            from ale_run.agents._bootstrap import ensure_npm
            npm = await ensure_npm()
        home = os.path.expanduser("~")
        env = self._base_env()
        env["npm_config_cache"] = os.path.join(home, ".npm-pi")
        proc = await asyncio.to_thread(
            subprocess.run,
            [npm, "install", "-g", "--prefix", prefix, package],
            capture_output=True, text=True, timeout=420, env=env,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"pi: npm install -g {package} failed (rc={proc.returncode}): "
                f"{(proc.stderr or proc.stdout or '')[-600:]}"
            )
        logger.info("pi: installed via npm -- %s", (proc.stdout or "").strip()[-160:])

    # =========================================================================
    # launch
    # =========================================================================

    async def launch(self, prompt: str) -> AgentRunResult:
        cfg: PiConfig = self.config  # type: ignore[assignment]
        wd = Path(self.executor.work_dir)
        wd.mkdir(parents=True, exist_ok=True)

        prompt_file = wd / "prompt.txt"
        transcript_file = wd / "transcript.jsonl"
        stderr_log = wd / "stderr.log"
        pid_file = wd / "pi.pid"

        for f in (transcript_file, stderr_log, pid_file):
            if f.exists():
                try:
                    f.unlink()
                except OSError:
                    pass
        prompt_file.write_text(prompt, encoding="utf-8")

        argv = self._build_argv(cfg, prompt)
        env = self._build_env(cfg)
        logger.info("pi: argv=%s", argv[:-1] + ["<prompt>"])

        t0 = time.monotonic()
        with open(transcript_file, "wb") as tout, open(stderr_log, "wb") as terr:
            proc = await asyncio.to_thread(
                subprocess.Popen,
                argv,
                stdin=subprocess.DEVNULL,   # pi blocks on stdin in --mode json
                stdout=tout,
                stderr=terr,
                env=env,
                cwd=str(wd),
                start_new_session=True if hasattr(os, "setsid") else False,
            )
        pid_file.write_text(str(proc.pid), encoding="ascii")
        logger.info("pi: spawned pid=%s (model=%s)", proc.pid, cfg.model)

        # The episode wall budget is orchestration-owned: the executor wraps
        # launch() in asyncio.wait_for(timeout=timeout_s). If it fires we are
        # cancelled mid-await; reap the child before propagating.
        try:
            while proc.poll() is None:
                await asyncio.sleep(_POLL_INTERVAL_S)
        except asyncio.CancelledError:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(proc.wait), timeout=_TERM_GRACE_S,
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            raise

        duration_s = time.monotonic() - t0
        exit_code = proc.returncode
        status = "completed" if exit_code == 0 else "failed"
        error: str | None = None
        if status == "failed":
            error = self._diagnose_failure(stderr_log, transcript_file, exit_code)
        # 即便 exit 0,也要看轨迹末尾有没有 LLM 层错误:pi 会把 402/网关 5xx 等
        # 运行时故障吞成 exit 0,纯看退出码会记 completed 打假零分。倒序扫轨迹,
        # 若最后一条 assistant 的 stopReason 是 error/aborted,则改判 failed。
        if status == "completed":
            llm_err = detect_llm_error_stop(transcript_file)
            if llm_err:
                status = "failed"
                error = (
                    "LLM error stop (exit 0 but stopReason=error): "
                    f"{llm_err[:400]}"
                )

        return AgentRunResult(
            status=status,
            pid=proc.pid,
            exit_code=exit_code,
            transcript_path=str(transcript_file),
            stderr_path=str(stderr_log),
            duration_s=duration_s,
            error=error,
        )

    def _build_argv(self, cfg: PiConfig, prompt: str) -> list[str]:
        argv = [
            self._pi_path,
            "--mode", "json",
            "--provider", cfg.provider,
            "--model", cfg.model,
            "--no-session",
            "--approve",
            "--thinking", cfg.thinking,
        ]
        if cfg.no_context_files:
            argv.append("--no-context-files")
        if cfg.disabled_tools:
            argv += ["--exclude-tools", ",".join(cfg.disabled_tools)]
        argv.append(prompt)   # prompt is the final positional arg
        return argv

    def _build_env(self, cfg: PiConfig) -> dict[str, str]:
        env = self._base_env()
        env["PI_CODING_AGENT_DIR"] = str(self._pi_config_dir())
        env["PI_OFFLINE"] = "1"
        env["PI_SKIP_VERSION_CHECK"] = "1"
        env["PI_TELEMETRY"] = "0"
        env["NO_COLOR"] = "1"
        env["HOME"] = os.path.expanduser("~")
        for k, v in cfg.extra_envs.items():
            env[str(k)] = str(v)
        return env

    def _diagnose_failure(
        self, stderr_log: Path, transcript: Path, exit_code: int | None,
    ) -> str:
        parts = [f"agent failed (rc={exit_code})"]
        se = _read_text_tolerant(stderr_log)
        tx = _read_text_tolerant(transcript)
        if se.strip():
            parts.append(f"stderr tail: ...{se[-800:]}")
        if tx.strip():
            parts.append(f"transcript tail: ...{tx[-600:]}")
        return " | ".join(parts)

    # =========================================================================
    # parse_artifacts
    # =========================================================================

    @classmethod
    def parse_artifacts(
        cls,
        *,
        work_dir: Path,
        config: PiConfig,
        run_result: AgentRunResult,
        builder: TrajectoryBuilder,
    ) -> None:
        transcript_file = work_dir / "transcript.jsonl"
        if not transcript_file.exists():
            builder.add_step(
                source="system",
                message=f"pi: no transcript at {transcript_file}",
                extra={"reason": "no_transcript"},
            )
            return

        raw = transcript_file.read_text(encoding="utf-8", errors="replace")
        # 只按真正的换行 \n 切 NDJSON:str.splitlines() 会把 U+2028/U+2029/NEL
        # 等 Unicode 行界也当换行,消息文本里含这些字符时会把整条 JSON 事件从中间
        # 撕开、json.loads 失败被丢弃,导致轨迹静默缺步。split("\n") 后每行可能带
        # 尾部 \r(\r\n),下面的 line.strip() 会一并去掉,\r\n 仍兼容。
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            cls._consume_event(event, builder)

        builder.trajectory.extra.setdefault("pi", {}).update({
            "exit_code": run_result.exit_code,
            "transcript_path": str(transcript_file),
        })

    # --- event handling ---

    @classmethod
    def _consume_event(cls, event: dict, builder: TrajectoryBuilder) -> None:
        etype = event.get("type")
        if etype == "session":
            builder.trajectory.extra.setdefault("pi", {})["session"] = {
                "id": event.get("id"), "version": event.get("version"),
            }
            return
        # We reconstruct the trajectory from the authoritative ``message_end``
        # events (each carries the full message: role, content, usage). The
        # tool_execution_* events duplicate the tool call/result and are skipped
        # to avoid double-counting.
        if etype != "message_end":
            return
        msg = event.get("message") or {}
        role = msg.get("role")
        if role == "user":
            cls._consume_user(msg, builder)
        elif role == "assistant":
            cls._consume_assistant(msg, builder)
        elif role == "toolResult":
            cls._consume_tool_result(msg, builder)

    @staticmethod
    def _text_of(content: Any) -> str:
        if isinstance(content, str):
            return content
        parts: list[str] = []
        for c in content or []:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(c.get("text", ""))
        return "".join(parts)

    @classmethod
    def _consume_user(cls, msg: dict, builder: TrajectoryBuilder) -> None:
        text = cls._text_of(msg.get("content"))
        if text.strip():
            builder.add_step(source="user", message=text)

    @classmethod
    def _consume_assistant(cls, msg: dict, builder: TrajectoryBuilder) -> None:
        reasoning_parts: list[str] = []
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for c in msg.get("content") or []:
            if not isinstance(c, dict):
                continue
            ctype = c.get("type")
            if ctype == "thinking":
                t = c.get("thinking", "")
                if t:
                    reasoning_parts.append(t)
            elif ctype == "text":
                text_parts.append(c.get("text", ""))
            elif ctype == "toolCall":
                args = c.get("arguments", {})
                if not isinstance(args, dict):
                    args = {"raw": args}
                tool_calls.append(ToolCall(
                    id=c.get("id", ""),
                    name=c.get("name", ""),
                    arguments=args,
                ))
        message = "".join(text_parts) or None
        reasoning = "\n".join(reasoning_parts) or None
        metrics = cls._usage_to_metrics(msg.get("usage"))
        # Only emit a step if it carries signal.
        if message or reasoning or tool_calls or metrics:
            builder.add_step(
                source="agent",
                message=message,
                reasoning=reasoning,
                tool_calls=tool_calls or None,
                metrics=metrics,
                extra={"stop_reason": msg.get("stopReason")} if msg.get("stopReason") else None,
            )

    @classmethod
    def _consume_tool_result(cls, msg: dict, builder: TrajectoryBuilder) -> None:
        content: list[ContentPart] = []
        for c in msg.get("content") or []:
            if not isinstance(c, dict):
                content.append(ContentPart(type="text", text=str(c)))
                continue
            if c.get("type") == "text":
                content.append(ContentPart(type="text", text=c.get("text", "")))
            else:
                content.append(ContentPart(type="text", text=json.dumps(c)))
        if not content:
            content = [ContentPart(type="text", text="")]
        builder.add_step(
            source="environment",
            observation=Observation(results=[
                ToolResult(
                    tool_call_id=msg.get("toolCallId", ""),
                    content=content,
                    is_error=bool(msg.get("isError")),
                ),
            ]),
        )

    @staticmethod
    def _usage_to_metrics(usage: Any) -> StepMetrics | None:
        if not isinstance(usage, dict) or not usage:
            return None
        cost = usage.get("cost")
        cost_usd = None
        if isinstance(cost, dict):
            cost_usd = cost.get("total")
        return StepMetrics(
            input_tokens=int(usage.get("input", 0) or 0),
            output_tokens=int(usage.get("output", 0) or 0),
            cache_read_tokens=int(usage.get("cacheRead", 0) or 0) or None,
            cost_usd=float(cost_usd) if cost_usd else None,
        )


def _read_text_tolerant(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, OSError):
        return ""
