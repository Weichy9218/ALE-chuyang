"""Runner: yaml-described experiment → concurrent run units.

Per-unit isolation:
    - One fresh ``ale.make(task_path)`` per unit (env binds task at ctor)
    - One fresh deployer instance per unit (configs are per-run state)

Concurrency is a single ``asyncio.Semaphore`` sized to ``spec.concurrency``
(matches simprun's one-knob model). Each unit holds the slot for its
full lifetime — VM acquire + agent run + post-launch fan-out + eval —
so the cap is effectively "max VMs alive at once". Size to
``min(GCP quota, LLM rate-limit / N)``.

Provider is shared across units — real providers (gcloud) acquire
a fresh VM per ``acquire()`` call, so concurrent acquires give concurrent
VMs.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Iterable

from .factory import EnvironmentRouter
from .experiment_spec import ExperimentSpec, RunUnit, UnitResult

logger = logging.getLogger(__name__)


class Runner:
    """Owns the provider; produces and executes run units."""

    def __init__(self, spec: ExperimentSpec):
        self._spec = spec
        # Router resolves each unit's snapshot to its provider, building +
        # caching provider instances lazily (keeps --dry-run provider-free).
        self._router = EnvironmentRouter(spec.environment)
        self._output_root = Path(spec.output.root) / spec.name

    @property
    def spec(self) -> ExperimentSpec:
        return self._spec

    @property
    def output_root(self) -> Path:
        return self._output_root

    # ---- enumeration ----

    def enumerate_units(self) -> list[RunUnit]:
        """Cartesian product of agents × tasks × variants."""
        out: list[RunUnit] = []
        for agent in self._spec.agents:
            for task in self._spec.tasks:
                for vi in task.variants:
                    out.append(RunUnit(
                        agent_id=agent.id,
                        agent_spec=agent,
                        task_path=task.path,
                        variant_index=vi,
                    ))
        return out

    # ---- execution ----

    async def run(
        self,
        units: Iterable[RunUnit] | None = None,
    ) -> list[UnitResult]:
        """Run all units (or a filtered subset). Returns ``list[UnitResult]``.

        No aggregation, no summary — caller does whatever rollup it wants.
        """
        from .lifecycle import (
            get_shutdown_event,
            install_signal_handlers,
            run_one_unit,
        )

        install_signal_handlers()
        unit_list = list(units) if units is not None else self.enumerate_units()
        if not unit_list:
            logger.warning("Runner.run: no units to execute")
            return []

        self._output_root.mkdir(parents=True, exist_ok=True)

        n = self._spec.concurrency
        sem = asyncio.Semaphore(n)
        logger.info("runner: %d units, concurrency=%d", len(unit_list), n)

        async def _drive(u: RunUnit) -> UnitResult:
            logger.info("[%s] queued", u.slug)
            result = await run_one_unit(
                unit=u,
                router=self._router,
                output_root=self._output_root,
                artifacts=self._spec.artifacts,
                sem=sem,
                cleanup_mode=self._spec.cleanup_mode,
                prompt_suffix=self._spec.prompt_suffix,
                wall_time_s=self._spec.wall_time_s,
            )
            logger.info("[%s] done: status=%s score=%s duration=%.1fs",
                        u.slug, result.status, result.score, result.duration_s or 0)
            return result

        # system_issues.md 9.1: the SIGINT/SIGTERM handler sets a shutdown
        # event, but nothing consumed it — Ctrl-C left the gather running, so
        # only kill -9 stopped a batch, which skips each unit's finally
        # (env.close_async) and leaks its container (4-16 vCPU / 15-60GB),
        # eroding capacity for the next batch. Race unit completion against the
        # shutdown event; on shutdown, cancel in-flight units so each runs its
        # finally teardown, then return whatever partial results completed.
        tasks = [asyncio.ensure_future(_drive(u)) for u in unit_list]
        shutdown = get_shutdown_event()
        shutdown_wait = asyncio.ensure_future(shutdown.wait())
        # return_exceptions=True: never raises, completes when all units are
        # done; individual outcomes are read back from `tasks` below.
        all_done = asyncio.gather(*tasks, return_exceptions=True)
        try:
            await asyncio.wait(
                {all_done, shutdown_wait}, return_when=asyncio.FIRST_COMPLETED,
            )
            if shutdown.is_set() and not all_done.done():
                pending = [t for t in tasks if not t.done()]
                logger.warning(
                    "runner: shutdown signal — cancelling %d in-flight unit(s) "
                    "so each tears down its container", len(pending),
                )
                for t in pending:
                    t.cancel()
                # Let every cancelled unit run its finally (container cleanup).
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            if not shutdown_wait.done():
                shutdown_wait.cancel()
            if not all_done.done():
                all_done.cancel()
            try:
                await all_done
            except asyncio.CancelledError:
                pass

        # Collect per-unit results. On the normal path an unexpected unit
        # exception propagates (preserving the old return_exceptions=False
        # contract); during shutdown, cancelled/errored units are skipped.
        results: list[UnitResult] = []
        for t in tasks:
            if t.cancelled():
                continue
            exc = t.exception()
            if exc is not None:
                if shutdown.is_set():
                    continue
                raise exc
            results.append(t.result())
        return results
