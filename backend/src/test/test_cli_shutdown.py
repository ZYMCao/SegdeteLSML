import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

CLI_SCRIPT = """
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from fastapi import FastAPI
from segdete import cli
from segdete.pipeline import processor

source = Path(os.environ["PYTHONPATH"]) / "segdete"
assert Path(cli.__file__).resolve() == source / "cli.py"
assert Path(processor.__file__).resolve() == source / "pipeline" / "processor.py"
os.environ["MQTT_TOKEN"] = "test-device"
settings = cli.load_settings()
settings.runtime.interval_sec = 60
settings.runtime.prewarm_frames = 0
settings.storage.save_root = sys.argv[2]
settings.web.port = 0
camera = Mock(sn_list=["left", "right"])
camera.close.side_effect = lambda: print("CLOSE:" + threading.current_thread().name, flush=True)

class Client:
    access_token = "test-device"
    def __init__(self, settings, commands):
        self.commands = commands
    def connect(self):
        if sys.argv[1] == "paused":
            self.commands.put(("setSystemRunning", False, lambda _: print("READY", flush=True)))
    def disconnect(self):
        print("DISCONNECT", flush=True)

cli.load_settings = lambda: settings
cli.parse_arguments = lambda: SimpleNamespace(
    no_web=sys.argv[3] == "no-web", web_fps=None, web_save_dir=None,
    host="127.0.0.1", port=0,
)
cli.create_web_app = lambda *_: FastAPI()
def preview(camera):
    while camera.web_running:
        threading.Event().wait(0.01)
    print("PREVIEW_STOPPED", flush=True)
cli.web_preview_loop = preview
cli.setup_logging = lambda _: None
cli._print_startup_diagnostics = lambda: None
cli.init_yolo_config = lambda _: None
cli.ThreadSafeCameraManager = lambda **_: camera
cli.TBEdgeClient = Client
processor.MLClassifier = lambda: object()
processor.StereoRectifier = lambda _: object()
processor.process_one_cycle = lambda **_: print("READY", flush=True)
cli.main()
print("STOPPED", flush=True)
"""


@pytest.mark.parametrize("state", ["running", "paused"])
@pytest.mark.parametrize("stop_signal", [signal.SIGTERM, signal.SIGINT])
@pytest.mark.parametrize("mode", ["no-web", "web"])
def test_cli_signal_stops_command_consumer(tmp_path, state, stop_signal, mode):
    with subprocess.Popen(
        [sys.executable, "-u", "-c", CLI_SCRIPT, state, str(tmp_path), mode],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        },
    ) as child:
        output = b""
        try:
            deadline = time.monotonic() + 15
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                while b"READY\n" not in output or (
                    mode == "web" and b"Uvicorn running on" not in output
                ):
                    remaining = deadline - time.monotonic()
                    assert remaining > 0, output.decode()
                    assert selector.select(remaining), output.decode()
                    chunk = os.read(child.stdout.fileno(), 4096)
                    assert chunk, output.decode()
                    output += chunk
            child.send_signal(stop_signal)
            output += child.communicate(timeout=5)[0]
            assert child.returncode == 0, output.decode()
            assert b"CLOSE:SegDeteProcessing" in output, output.decode()
            assert b"DISCONNECT" in output, output.decode()
            assert b"STOPPED" in output, output.decode()
            if mode == "web":
                assert b"PREVIEW_STOPPED" in output, output.decode()
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()
