import threading
from unittest.mock import Mock

import pytest
from segdete.pipeline import processor


def finish_after_commands(env):
    completed = []

    def finish(value):
        completed.append(value)
        env.shutdown.set()

    env.commands.put(("setIntervalSec", 10, finish))
    env.run()
    assert completed == [10], "An earlier command prevented later commands from running"
    env.camera.close.assert_called_once_with()


@pytest.mark.parametrize("initial", [False, True])
def test_failed_camera_transition_preserves_state_without_success_ack(
    processing_env, initial
):
    env = processing_env
    if not initial:
        env.running.clear()
    action = env.camera.stop if initial else env.camera.start
    action.side_effect = RuntimeError("device unavailable")
    acknowledgments = []
    env.commands.put(("setSystemRunning", not initial, acknowledgments.append))

    finish_after_commands(env)

    assert env.running.is_set() == initial
    assert acknowledgments == []
    action.assert_called_once_with()


@pytest.mark.parametrize("failure", [False, RuntimeError("device unavailable")])
def test_failed_exposure_is_not_acknowledged_and_consumer_survives(
    processing_env, failure
):
    env = processing_env
    env.camera.set_exp.side_effect = [True, failure]
    acknowledgments = []
    env.commands.put(("setExposureTime", 1000, acknowledgments.append))

    finish_after_commands(env)

    assert acknowledgments == []


@pytest.mark.parametrize(
    ("command", "value"),
    [
        ("setSystemRunning", False),
        ("setIntervalSec", 20),
        ("setExposureTime", 1000),
        ("setFrameRate", 8),
    ],
)
def test_ack_exception_does_not_stop_later_commands(processing_env, command, value):
    env = processing_env
    ack = Mock(side_effect=RuntimeError("connection lost"))
    env.commands.put((command, value, ack))

    finish_after_commands(env)

    ack.assert_called_once_with(value)


def test_duplicate_transitions_are_idempotent_and_keep_fifo_order(processing_env):
    env = processing_env
    acknowledgments = []
    for value in (False, False, True, True):
        env.commands.put(("setSystemRunning", value, acknowledgments.append))

    finish_after_commands(env)

    assert acknowledgments == [False, False, True, True]
    env.camera.stop.assert_called_once_with()
    env.camera.start.assert_called_once_with()


def test_unknown_command_has_no_success_ack_and_consumer_survives(processing_env):
    env = processing_env
    ack = Mock()
    env.commands.put(("unknownCommand", 123, ack))

    finish_after_commands(env)

    ack.assert_not_called()
    processor.process_one_cycle.assert_not_called()


def test_runtime_camera_failure_disconnects_mqtt(processing_env):
    env = processing_env
    env.camera.is_available.return_value = True
    disconnected = threading.Event()
    env.client.disconnect.side_effect = disconnected.set

    def lose_camera(**_):
        env.camera.is_available.return_value = False

    processor.process_one_cycle.side_effect = lose_camera
    thread = threading.Thread(target=env.run, daemon=True)
    thread.start()
    try:
        assert disconnected.wait(timeout=1)
        assert not env.running.is_set()
        env.client.disconnect.assert_called_once_with()
    finally:
        env.shutdown.set()
        thread.join(timeout=1)
    assert not thread.is_alive()


def test_camera_loss_while_paused_disconnects_mqtt(processing_env):
    env = processing_env
    env.running.clear()
    checked = threading.Event()
    disconnected = threading.Event()
    state = {"available": True}

    def is_available():
        checked.set()
        return state["available"]

    env.camera.is_available.side_effect = is_available
    env.client.disconnect.side_effect = disconnected.set
    thread = threading.Thread(target=env.run, daemon=True)
    thread.start()
    try:
        assert checked.wait(timeout=1)
        state["available"] = False
        assert disconnected.wait(timeout=1.5)
        processor.process_one_cycle.assert_not_called()
    finally:
        env.shutdown.set()
        thread.join(timeout=1)
    assert not thread.is_alive()


def test_failed_capture_cycle_does_not_disconnect_mqtt(processing_env):
    env = processing_env
    completed = threading.Event()

    def failed_capture(**_):
        completed.set()
        env.shutdown.set()
        return False

    env.camera.is_available.return_value = True
    processor.process_one_cycle.side_effect = failed_capture
    thread = threading.Thread(target=env.run, daemon=True)
    thread.start()
    thread.join(timeout=1)

    assert completed.is_set()
    assert not thread.is_alive()
    env.client.disconnect.assert_not_called()
