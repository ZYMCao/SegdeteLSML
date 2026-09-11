import queue
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from segdete.config.settings import load_settings
from segdete.pipeline import processor
from segdete.pipeline.control import ShutdownEvent


@pytest.fixture
def processing_env(monkeypatch, tmp_path):
    settings = load_settings()
    settings.runtime.prewarm_frames = 0
    settings.storage.save_root = str(tmp_path)
    commands = queue.Queue()
    env = SimpleNamespace(
        settings=settings,
        commands=commands,
        running=threading.Event(),
        shutdown=ShutdownEvent(commands),
        camera=Mock(sn_list=["left", "right"]),
        client=Mock(access_token="test-device"),
    )
    env.running.set()
    monkeypatch.setattr(processor, "MLClassifier", Mock())
    monkeypatch.setattr(processor, "StereoRectifier", Mock())
    monkeypatch.setattr(processor, "process_one_cycle", Mock(return_value=True))

    def run():
        processor.segdete_processing_loop(
            env.camera, env.client, env.settings,
            env.commands, env.running, env.shutdown,
        )

    env.run = run
    return env
