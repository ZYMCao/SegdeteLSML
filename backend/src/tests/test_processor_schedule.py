import heapq
import itertools
import queue
from types import SimpleNamespace

import pytest
from segdete.pipeline import processor
from segdete.pipeline.control import ShutdownEvent


class Clock:
    now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ScheduledCommands:
    def __init__(self, clock):
        self.clock = clock
        self.items = []
        self.sequence = itertools.count()

    def at(self, when, command):
        heapq.heappush(self.items, (when, next(self.sequence), command))

    def put(self, command):
        self.at(self.clock.now, command)

    def get(self, timeout=None):
        deadline = float("inf") if timeout is None else self.clock.now + timeout
        if self.items and self.items[0][0] <= deadline:
            when, _, command = heapq.heappop(self.items)
            self.clock.now = max(self.clock.now, when)
            return command
        assert timeout is not None, "No event can wake this paused simulation"
        self.clock.now = deadline
        raise queue.Empty


@pytest.fixture
def schedule(processing_env, monkeypatch):
    env = processing_env
    clock = Clock()
    commands = ScheduledCommands(clock)
    env.commands = commands
    env.shutdown = ShutdownEvent(commands)
    monkeypatch.setattr(processor, "time", clock)
    starts = []

    def run(interval, durations=(0, 0)):
        env.settings.runtime.interval_sec = interval

        def cycle(**_):
            starts.append(clock.now)
            clock.sleep(durations[len(starts) - 1])
            if len(starts) == len(durations):
                env.shutdown.set()

        monkeypatch.setattr(processor, "process_one_cycle", cycle)
        env.run()
        assert len(starts) == len(durations)
        return starts

    return SimpleNamespace(env=env, clock=clock, commands=commands, run=run)


@pytest.mark.parametrize(
    ("initial", "changed_at", "new_interval", "expected_next"),
    [(60, 25, 40, 40), (60, 25, 10, 25), (10, 5, 20, 20)],
)
def test_interval_change_is_relative_to_last_cycle_end(
    schedule, initial, changed_at, new_interval, expected_next
):
    schedule.commands.at(changed_at, ("setIntervalSec", new_interval, None))

    assert schedule.run(initial) == [0, expected_next]


def test_capture_interval_starts_after_processing_finishes(schedule):
    assert schedule.run(10, durations=(7, 25, 2)) == [0, 17, 52]


def test_commands_neither_advance_nor_delay_the_capture_deadline(schedule):
    acknowledgments = []
    for when, command, value in (
        (2, "setExposureTime", 1000),
        (6, "setSystemRunning", True),
        (9, "setExposureTime", 2000),
        (13, "setFrameRate", 8),
    ):
        schedule.commands.at(when, (command, value, acknowledgments.append))

    assert schedule.run(10, durations=(7, 0)) == [0, 17]
    assert acknowledgments == [1000, True, 2000, 8]
    schedule.env.camera.start.assert_not_called()


@pytest.mark.parametrize("value", [-1, True, 2.0, "1.5", None, "bad"])
def test_invalid_interval_keeps_schedule_and_does_not_ack(schedule, value):
    acknowledgments = []
    schedule.commands.at(2, ("setIntervalSec", value, acknowledgments.append))

    assert schedule.run(10) == [0, 10]
    assert acknowledgments == []


def test_zero_interval_keeps_continuous_capture_supported(schedule):
    acknowledgments = []
    schedule.commands.at(2, ("setIntervalSec", 0, acknowledgments.append))

    assert schedule.run(10) == [0, 2]
    assert acknowledgments == [0]
