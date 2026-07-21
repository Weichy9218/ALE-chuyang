"""Writer-triggered pre-submission runs of the frozen verifier suite.

The frozen suite exists before the Writer starts, but until v15 its first
execution waited for DONE, so every measurement arrived after the Writer had
spent its budget. This tool moves the same measurement before submission: the
Writer calls ``verify`` while it is still working, the harness snapshots the
current ``output/``, runs the complete frozen suite in the same Landlock/seccomp
isolation, and returns the same four-category report.

Nothing about the standard changes at call time: the suite content, hashes,
sources, and authority levels were all frozen before the Writer started, and
``execute_test_suite`` re-verifies suite hash, script hashes, and public source
hashes on every run. The only new information flow is that the Writer sees the
frozen test content earlier - which is already true of the post-DONE review
rounds this harness runs.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Union

from agent.tools.base import BaseTool

from .harness.tools._tool_utils import _run_async
from .verifier import FrozenTestSuite, build_feedback_prompt
from .verifier_runtime import (
    execute_test_suite,
    snapshot_manifest,
    snapshot_output,
    stage_test_suite,
    stage_verifier_report,
)

logger = logging.getLogger(__name__)

MAX_WRITER_CHECKS = 8


class WriterVerifyTool(BaseTool):
    """Run the frozen public verifier suite against the current ``output/``.

    The deployer constructs the tool before the suite exists and binds the
    frozen suite once the builder finishes; until then the tool reports that
    verification is unavailable. Every call consumes one of ``max_calls``
    pre-submission runs. Results are returned to the Writer verbatim and also
    persisted to the host run directory and the VM ``verifier/`` directory,
    so the post-DONE review loop and the analyzer see the same records.
    """

    name = "verify"

    def __init__(
        self,
        *,
        interface: Any,
        os_type: str,
        task_root: str,
        task_prompt: str,
        max_calls: int,
        work_dir: Path,
        cfg: dict | None = None,
    ):
        self.interface = interface
        self.os_type = os_type
        self.task_root = task_root
        self.task_prompt = task_prompt
        self.max_calls = max(0, min(int(max_calls), MAX_WRITER_CHECKS))
        self.work_dir = work_dir
        self.calls_used = 0
        self.records: list[dict[str, Any]] = []
        # Checks the writer has actually been shown. A dispute only counts
        # against a finding the writer saw; otherwise reading the check names
        # off a report would be enough to dismiss the whole review round.
        self.seen_checks: set[str] = set()
        self._suite: FrozenTestSuite | None = None
        self._staged = False
        self._unavailable_reason = "the verifier suite is still being built"
        self._lock = threading.Lock()
        super().__init__(cfg)

    # -- deployer wiring ----------------------------------------------------

    def bind_suite(self, suite: FrozenTestSuite) -> None:
        """Attach the frozen suite once the builder and auditor finish."""
        self._suite = suite
        self._unavailable_reason = ""

    def mark_unavailable(self, reason: str) -> None:
        self._suite = None
        self._unavailable_reason = reason or "the verifier suite is unavailable"

    @property
    def remaining_calls(self) -> int:
        return max(0, self.max_calls - self.calls_used)

    # -- BaseTool surface ---------------------------------------------------

    @property
    def description(self) -> str:
        return (
            "Run the frozen public verifier suite against a read-only snapshot "
            "of your current output/. The tests were derived from the public "
            "task materials and frozen before you started; running them does "
            "not change them. Returns hard mismatches (public hard "
            "requirements you currently violate), advisory review items, "
            "execution errors, and coverage gaps. Use it before you finish, "
            "when output/ holds a complete draft - a limited number of runs "
            "is available and an all-pass result only covers the publicly "
            "testable part of the task."
        )

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def call(self, params: Union[str, dict], **kwargs) -> dict:
        with self._lock:
            try:
                return _run_async(self._execute())
            except Exception as exc:  # noqa: BLE001 - never crash the writer loop
                logger.warning("writer verify call failed: %s", exc)
                return {
                    "success": False,
                    "error": f"Error: verification run failed: {exc}",
                }

    # -- execution ----------------------------------------------------------

    async def _execute(self) -> dict:
        if self._suite is None:
            return {
                "success": False,
                "error": f"Error: verification is unavailable: {self._unavailable_reason}",
            }
        if self.remaining_calls <= 0:
            return {
                "success": False,
                "error": (
                    f"Error: no verification runs remain (used {self.calls_used}"
                    f"/{self.max_calls}). Rely on your own checks; a final "
                    "verifier round may still run after you finish."
                ),
            }
        if not self._staged:
            self._suite = await stage_test_suite(
                interface=self.interface,
                task_root=self.task_root,
                manifest=self._suite.manifest,
            )
            self._staged = True

        started = time.monotonic()
        run_index = self.calls_used + 1
        snapshot = await snapshot_output(
            interface=self.interface,
            task_root=self.task_root,
            os_type=self.os_type,
            iteration=f"writer{run_index}",
        )
        result = await execute_test_suite(
            interface=self.interface,
            task_root=self.task_root,
            task_prompt=self.task_prompt,
            suite=self._suite,
            snapshot=snapshot,
        )
        self.calls_used = run_index

        record = result.metadata()
        record["iteration"] = f"writer{run_index}"
        record["phase"] = "pre_submission"
        record["snapshot_path"] = snapshot.path
        record["snapshot_file_count"] = snapshot.file_count
        record["snapshot_source_sha256"] = snapshot.source_sha256
        record["snapshot_manifest"] = await snapshot_manifest(
            self.interface, snapshot
        )
        record["duration_s"] = time.monotonic() - started
        report_path = await stage_verifier_report(
            self.interface,
            task_root=self.task_root,
            filename=f"writer_check_{run_index}.json",
            report=record,
        )
        record["writer_report_path"] = report_path
        self.records.append(record)
        try:
            (self.work_dir / f"verifier_writer_check_{run_index}.json").write_text(
                json.dumps(record, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("could not persist writer check record: %s", exc)

        self.seen_checks.update(
            check["check"] for check in result.hard_mismatches + result.review_items
        )
        feedback = build_feedback_prompt(
            result,
            report_path=report_path,
            pre_submission=True,
        )
        header = (
            f"PRE-SUBMISSION VERIFICATION RUN {run_index}/{self.max_calls} "
            f"(remaining after this run: {self.remaining_calls})\n"
            f"Snapshot: {snapshot.file_count} files, sha256 {snapshot.sha256[:16]}..."
        )
        return {"success": True, "output": f"{header}\n\n{feedback}"}
