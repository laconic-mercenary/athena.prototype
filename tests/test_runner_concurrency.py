"""Tests for the concurrency gate: engagements beyond capacity queue on the semaphore
and start when a slot frees. The real pipeline is stubbed — only the slot mechanics matter.
"""

import threading
import time

from athena import engagement_status
from athena.server import runner


def _make_engagement(run_id: str) -> runner.Engagement:
    return runner.Engagement(
        run_id=run_id,
        ensemble=object(),
        instructions="do the thing",
        orch_model="m",
        orch_provider="fake",
        orch_config={},
        project_name="default",
    )


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_engagement_beyond_capacity_queues_then_starts(monkeypatch) -> None:
    monkeypatch.setattr(runner, "_run_semaphore", threading.Semaphore(1))
    started: list[str] = []
    release = threading.Event()

    def make(run_id: str) -> runner.Engagement:
        eng = _make_engagement(run_id)

        def fake_run() -> None:
            eng.context.status = engagement_status.RUNNING
            started.append(run_id)
            release.wait(timeout=2)
            eng.context.status = engagement_status.COMPLETED

        # Instance attribute shadows Engagement.run so the slot mechanics run without the
        # real pipeline (no LLM backend, no SSE bus).
        monkeypatch.setattr(eng, "run", fake_run)
        return eng

    first = make("first")
    second = make("second")

    t1 = threading.Thread(target=runner._run_engagement, args=(first,))
    t1.start()
    assert _wait_until(lambda: first.context.status == engagement_status.RUNNING)

    t2 = threading.Thread(target=runner._run_engagement, args=(second,))
    t2.start()
    # The one slot is held by `first`, so `second` stays QUEUED and does not start.
    assert _wait_until(lambda: t2.is_alive())
    assert second.context.status == engagement_status.QUEUED
    assert started == ["first"]

    release.set()
    assert _wait_until(lambda: second.context.status == engagement_status.COMPLETED)
    assert started == ["first", "second"]
    t1.join(timeout=2)
    t2.join(timeout=2)


def test_aborted_queued_engagement_never_runs(monkeypatch) -> None:
    monkeypatch.setattr(runner, "_run_semaphore", threading.Semaphore(1))
    ran: list[str] = []
    release = threading.Event()

    holder = _make_engagement("holder")

    def holder_run() -> None:
        holder.context.status = engagement_status.RUNNING
        release.wait(timeout=2)

    monkeypatch.setattr(holder, "run", holder_run)

    waiting = _make_engagement("waiting")
    monkeypatch.setattr(waiting, "run", lambda: ran.append("waiting"))

    t1 = threading.Thread(target=runner._run_engagement, args=(holder,))
    t1.start()
    assert _wait_until(lambda: holder.context.status == engagement_status.RUNNING)

    t2 = threading.Thread(target=runner._run_engagement, args=(waiting,))
    t2.start()
    assert _wait_until(lambda: t2.is_alive())

    # Abort while queued, then free the slot: the run must be skipped.
    waiting.context.cancelled = True
    waiting.context.status = engagement_status.ABANDONED
    release.set()

    t1.join(timeout=2)
    t2.join(timeout=2)
    assert ran == []
    assert waiting.context.status == engagement_status.ABANDONED
