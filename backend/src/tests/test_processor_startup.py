import queue
import threading

import pytest
from segdete.pipeline import processor


@pytest.fixture
def run_processing_thread(processing_env):
    env = processing_env
    thread = threading.Thread(target=env.run, daemon=True)
    yield thread
    env.shutdown.set()
    if thread.ident is not None:
        thread.join(timeout=1)
        assert not thread.is_alive()


def send(env, command, value):
    acknowledgments = queue.Queue()
    env.commands.put((command, value, acknowledgments.put))
    return acknowledgments.get(timeout=0.75)


def test_initially_paused_loop_can_resume_prewarm(processing_env, run_processing_thread):
    env = processing_env
    env.running.clear()
    env.settings.runtime.prewarm_frames = 3
    env.camera.grab_frames.return_value = []
    captured = threading.Event()
    processor.process_one_cycle.side_effect = lambda **_: captured.set()
    run_processing_thread.start()

    assert send(env, "setSystemRunning", True) is True
    assert captured.wait(timeout=1)
    assert env.camera.grab_frames.call_count == 3


def test_pause_during_prewarm_stops_further_grabs_until_resume(
    processing_env, run_processing_thread
):
    env = processing_env
    env.settings.runtime.prewarm_frames = 3
    acknowledgments = queue.Queue()
    captured = threading.Event()

    def grab():
        if env.camera.grab_frames.call_count == 1:
            env.commands.put(("setSystemRunning", False, acknowledgments.put))
        return []

    env.camera.grab_frames.side_effect = grab
    processor.process_one_cycle.side_effect = lambda **_: captured.set()
    run_processing_thread.start()

    assert acknowledgments.get(timeout=0.75) is False
    assert env.camera.grab_frames.call_count == 1
    assert not captured.is_set()
    assert send(env, "setSystemRunning", True) is True
    assert captured.wait(timeout=1)
    assert env.camera.grab_frames.call_count == 3


def test_no_camera_mode_still_processes_control_commands(
    processing_env, run_processing_thread
):
    env = processing_env
    env.camera.sn_list = []
    exposure_acks = []
    env.commands.put(("setExposureTime", 1000, exposure_acks.append))
    run_processing_thread.start()

    assert send(env, "setIntervalSec", 30) == 30
    assert send(env, "setSystemRunning", False) is False
    assert send(env, "setSystemRunning", True) is True
    env.shutdown.set()
    run_processing_thread.join(timeout=0.75)

    assert not run_processing_thread.is_alive()
    processor.MLClassifier.assert_not_called()
    processor.StereoRectifier.assert_not_called()
    processor.process_one_cycle.assert_not_called()
    env.camera.grab_frames.assert_not_called()
    env.camera.close.assert_called_once_with()
    assert exposure_acks == []


@pytest.mark.parametrize("initializer", ["MLClassifier", "StereoRectifier"])
def test_initialization_failure_releases_cameras(processing_env, initializer, caplog):
    getattr(processor, initializer).side_effect = RuntimeError("initialization failed")

    processing_env.run()

    processing_env.camera.close.assert_called_once_with()
    processor.process_one_cycle.assert_not_called()
    assert "initialization failed" in caplog.text


def test_shutdown_during_prewarm_releases_camera_after_grab_finishes(
    processing_env, run_processing_thread
):
    env = processing_env
    env.settings.runtime.prewarm_frames = 3
    grabbing = threading.Event()
    release = threading.Event()

    def grab():
        grabbing.set()
        release.wait(timeout=2)

    env.camera.grab_frames.side_effect = grab
    run_processing_thread.start()
    try:
        assert grabbing.wait(timeout=1)
        env.shutdown.set()
    finally:
        release.set()
    run_processing_thread.join(timeout=1)

    assert not run_processing_thread.is_alive()
    env.camera.close.assert_called_once_with()
    assert env.camera.grab_frames.call_count == 1
    processor.process_one_cycle.assert_not_called()
