"""Tests for the PyPubSub -> asyncio.Queue SSE bridge, focused on multi-listener fan-out:
a single run_id can feed several open SSE streams at once.
"""

import asyncio

from pubsub import pub

from athena.server import bus

_TEST_TOPIC = "test.bus.fanout"


def test_create_queue_registers_multiple_listeners_per_run() -> None:
    q1 = bus.create_queue("run-multi")
    q2 = bus.create_queue("run-multi")
    try:
        assert bus._queues["run-multi"] == {q1, q2}
        bus.remove_queue("run-multi", q1)
        assert bus._queues["run-multi"] == {q2}
        bus.remove_queue("run-multi", q2)
        assert "run-multi" not in bus._queues  # key dropped once the last stream closes
    finally:
        bus._queues.pop("run-multi", None)


def test_bridge_fans_out_to_all_listeners() -> None:
    original_loop = bus._loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    q1 = bus.create_queue("run-fan")
    q2 = bus.create_queue("run-fan")
    try:
        bus.register_loop(loop)
        pub.sendMessage(_TEST_TOPIC, run_id="run-fan")
        loop.run_until_complete(asyncio.sleep(0))  # drain the call_soon_threadsafe callbacks
        e1 = q1.get_nowait()
        e2 = q2.get_nowait()
        assert e1["topic"] == _TEST_TOPIC
        assert e2["topic"] == _TEST_TOPIC
        assert e1["run_id"] == "run-fan" and e2["run_id"] == "run-fan"
    finally:
        bus.remove_queue("run-fan", q1)
        bus.remove_queue("run-fan", q2)
        bus.register_loop(original_loop)
        loop.close()
        asyncio.set_event_loop(None)


def test_bridge_ignores_events_without_a_listener() -> None:
    original_loop = bus._loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        bus.register_loop(loop)
        pub.sendMessage(_TEST_TOPIC, run_id="run-nobody")  # no queue registered -> no-op
        loop.run_until_complete(asyncio.sleep(0))
        assert "run-nobody" not in bus._queues
    finally:
        bus.register_loop(original_loop)
        loop.close()
        asyncio.set_event_loop(None)
