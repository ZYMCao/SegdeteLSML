from pseudocamera.run import CAMEMU_SERIALS, build_run_env, launch


def test_build_run_env_sets_exactly_five_vars(tmp_path):
    frames = tmp_path / "frames"
    (frames / "left").mkdir(parents=True)
    (frames / "right").mkdir()
    env = build_run_env(frames, camemu=2)
    assert env == {
        "PYLON_CAMEMU": "2",
        "SEGDETE_CAMERA_SNS": ",".join(CAMEMU_SERIALS),
        "SEGDETE_PIXEL_FORMAT": "RGB8Packed",
        "PSEUDOCAMERA_LEFT_DIR": str((frames / "left").resolve()),
        "PSEUDOCAMERA_RIGHT_DIR": str((frames / "right").resolve()),
    }
    assert CAMEMU_SERIALS == ("0815-0000", "0815-0001")


def test_launch_prepends_pseudocamera_src_to_pythonpath(monkeypatch):
    captured = {}

    class _Result:
        returncode = 0

    def fake_run(command, env):
        captured["command"] = command
        captured["env"] = env
        return _Result()

    monkeypatch.setattr("pseudocamera.run.subprocess.run", fake_run)
    monkeypatch.setenv("PYTHONPATH", "/existing/entries")
    code = launch(["target"], {"PYLON_CAMEMU": "2"})
    assert code == 0
    parts = captured["env"]["PYTHONPATH"].split(":")
    assert parts[0].endswith("pseudocamera/src")
    assert parts[1] == "/existing/entries"
    assert captured["env"]["PYLON_CAMEMU"] == "2"
    assert captured["command"] == ["target"]
