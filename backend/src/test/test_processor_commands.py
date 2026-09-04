import queue
import threading
import time
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from segdete.pipeline import processor
from segdete.pipeline.control import ShutdownEvent


@pytest.fixture
def start_loop(processing_env, monkeypatch):
    loops = []

    def start(interval=60, cycle=None):
        settings = deepcopy(processing_env.settings)
        settings.runtime.interval_sec = interval
        loop = SimpleNamespace(
            commands=queue.Queue(),
            cycles=queue.Queue(),
            running=threading.Event(),
            camera=Mock(sn_list=["left", "right"]),
        )
        loop.shutdown = ShutdownEvent(loop.commands)
        loop.running.set()

        def process_cycle(**kwargs):
            loop.cycles.put(kwargs["loop_count"])
            if cycle:
                cycle()

        monkeypatch.setattr(processor, "process_one_cycle", process_cycle)
        loop.thread = threading.Thread(
            target=processor.segdete_processing_loop,
            args=(
                loop.camera,
                SimpleNamespace(access_token="device"),
                settings,
                loop.commands,
                loop.running,
                loop.shutdown,
            ),
            daemon=True,
        )
        loops.append(loop)
        loop.thread.start()
        assert loop.cycles.get(timeout=1) == 1
        return loop

    yield start

    for loop in loops:
        loop.shutdown.set()
        loop.thread.join(timeout=1)
        assert not loop.thread.is_alive()


def send_command(loop, name, value):
    acknowledgments = queue.Queue()
    loop.commands.put((name, value, acknowledgments.put))
    return acknowledgments.get(timeout=0.75)


def test_command_wakes_capture_wait_without_starting_another_cycle(start_loop):
    loop = start_loop()

    assert send_command(loop, "setExposureTime", 1000) == 1000
    loop.camera.set_exp.assert_has_calls([call(0, 1000), call(1, 1000)])
    with pytest.raises(queue.Empty):
        loop.cycles.get(timeout=0.1)


def test_pause_and_resume_wake_without_waiting_for_capture_interval(start_loop):
    loop = start_loop()

    assert send_command(loop, "setSystemRunning", False) is False
    assert not loop.running.is_set()
    loop.camera.stop.assert_called_once_with()
    assert send_command(loop, "setExposureTime", 2000) == 2000
    with pytest.raises(queue.Empty):
        loop.cycles.get(timeout=0.1)

    assert send_command(loop, "setSystemRunning", True) is True
    assert loop.cycles.get(timeout=0.75) == 2
    loop.camera.start.assert_called_once_with()


def test_shorter_interval_applies_to_current_wait(start_loop):
    loop = start_loop()

    assert send_command(loop, "setIntervalSec", 1) == 1
    assert loop.cycles.get(timeout=1.5) == 2


def test_resume_and_interval_change_in_same_batch_capture_immediately(start_loop):
    loop = start_loop()
    acknowledgments = queue.Queue()

    def resume_with_new_interval(_):
        loop.commands.put(("setSystemRunning", True, acknowledgments.put))
        loop.commands.put(("setIntervalSec", 30, acknowledgments.put))

    loop.commands.put(("setSystemRunning", False, resume_with_new_interval))

    assert acknowledgments.get(timeout=0.75) is True
    assert acknowledgments.get(timeout=0.75) == 30
    assert loop.cycles.get(timeout=0.75) == 2


def test_longer_interval_postpones_next_capture(start_loop):
    loop = start_loop(interval=1)

    assert send_command(loop, "setIntervalSec", 60) == 60
    with pytest.raises(queue.Empty):
        loop.cycles.get(timeout=1.2)


def test_other_commands_do_not_reset_capture_deadline(start_loop):
    loop = start_loop(interval=2)

    for exposure in (1000, 2000, 3000, 4000):
        time.sleep(0.4)
        assert send_command(loop, "setExposureTime", exposure) == exposure

    assert loop.cycles.get(timeout=0.9) == 2


def test_command_received_during_cycle_runs_as_soon_as_cycle_finishes(start_loop):
    release_cycle = threading.Event()
    loop = start_loop(cycle=lambda: release_cycle.wait(timeout=2))
    acknowledgments = queue.Queue()
    loop.commands.put(("setExposureTime", 1000, acknowledgments.put))

    try:
        with pytest.raises(queue.Empty):
            acknowledgments.get(timeout=0.1)
    finally:
        release_cycle.set()

    assert acknowledgments.get(timeout=0.75) == 1000


@pytest.mark.parametrize("paused", [False, True])
def test_shutdown_wakes_idle_loop(start_loop, paused):
    loop = start_loop()
    if paused:
        assert send_command(loop, "setSystemRunning", False) is False

    loop.shutdown.set()
    loop.thread.join(timeout=0.75)

    assert not loop.thread.is_alive()
    loop.camera.close.assert_called_once_with()
