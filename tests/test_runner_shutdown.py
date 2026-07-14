#!/usr/bin/env python3
"""Verify system_issues 9.1: a shutdown signal cancels in-flight units so each
runs its finally (container teardown), instead of leaking on kill -9.

This exercises the exact asyncio race/cancel pattern used in
ale_run/orchestration/runner.py Runner.run (racing an all-units gather against
a shutdown event, then cancelling pending units and awaiting their finallys).
Stubs stand in for run_one_unit so no ale_run deps / Docker are needed.
"""
import asyncio


def _fail(msg):
    print(f"FAIL: {msg}")
    raise SystemExit(1)


async def _run_batch(drive_fns, shutdown_event):
    """Faithful copy of Runner.run's completion/shutdown handling."""
    tasks = [asyncio.ensure_future(fn()) for fn in drive_fns]
    shutdown_wait = asyncio.ensure_future(shutdown_event.wait())
    all_done = asyncio.gather(*tasks, return_exceptions=True)
    try:
        await asyncio.wait(
            {all_done, shutdown_wait}, return_when=asyncio.FIRST_COMPLETED,
        )
        if shutdown_event.is_set() and not all_done.done():
            pending = [t for t in tasks if not t.done()]
            for t in pending:
                t.cancel()
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

    results = []
    for t in tasks:
        if t.cancelled():
            continue
        exc = t.exception()
        if exc is not None:
            if shutdown_event.is_set():
                continue
            raise exc
        results.append(t.result())
    return results


def test_normal_path_returns_all_results():
    async def go():
        async def mk(i):
            async def fn():
                await asyncio.sleep(0.01)
                return f"unit-{i}"
            return fn
        drive = [await mk(i) for i in range(4)]
        ev = asyncio.Event()  # never set
        results = await _run_batch(drive, ev)
        if sorted(results) != ["unit-0", "unit-1", "unit-2", "unit-3"]:
            _fail(f"normal path lost results: {results}")
    asyncio.run(go())
    print("PASS: test_normal_path_returns_all_results")


def test_shutdown_cancels_and_runs_finally():
    async def go():
        cleaned = []          # records units whose finally ran (container teardown)
        finished = []

        def mk(i, slow):
            async def fn():
                try:
                    await asyncio.sleep(0.5 if slow else 0.01)
                    finished.append(i)
                    return f"unit-{i}"
                finally:
                    # This is the env.close_async / container-teardown slot.
                    cleaned.append(i)
            return fn

        # units 0,1 finish fast; 2,3 are slow and should be cancelled.
        drive = [mk(0, False), mk(1, False), mk(2, True), mk(3, True)]
        ev = asyncio.Event()

        async def trip():
            await asyncio.sleep(0.05)   # after fast units, during slow ones
            ev.set()

        trip_task = asyncio.ensure_future(trip())
        results = await _run_batch(drive, ev)
        await trip_task

        # Fast units returned their results.
        if sorted(results) != ["unit-0", "unit-1"]:
            _fail(f"expected partial results from fast units, got {results}")
        # Slow units were cancelled (never appended to finished)...
        if 2 in finished or 3 in finished:
            _fail("slow units should have been cancelled before finishing")
        # ...but EVERY unit's finally ran — no leaked container.
        if sorted(cleaned) != [0, 1, 2, 3]:
            _fail(f"not all units ran their finally cleanup: {cleaned}")

    asyncio.run(go())
    print("PASS: test_shutdown_cancels_and_runs_finally")


def test_normal_path_propagates_unit_exception():
    async def go():
        def mk_ok():
            async def fn():
                await asyncio.sleep(0.01)
                return "ok"
            return fn

        def mk_boom():
            async def fn():
                await asyncio.sleep(0.01)
                raise ValueError("unit blew up")
            return fn

        ev = asyncio.Event()  # never set -> normal path must re-raise
        raised = False
        try:
            await _run_batch([mk_ok(), mk_boom()], ev)
        except ValueError as e:
            raised = "unit blew up" in str(e)
        if not raised:
            _fail("normal path should propagate a unit exception (old contract)")
    asyncio.run(go())
    print("PASS: test_normal_path_propagates_unit_exception")


if __name__ == "__main__":
    test_normal_path_returns_all_results()
    test_shutdown_cancels_and_runs_finally()
    test_normal_path_propagates_unit_exception()
    print("\nALL PASSED: shutdown cancels units + runs finally teardown (9.1)")
