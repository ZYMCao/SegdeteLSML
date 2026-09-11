from segdete.pipeline import processor


def test_continuous_commands_cannot_starve_due_capture(processing_env, monkeypatch):
    env = processing_env
    acknowledgments = []
    captures = []

    def produce(value):
        acknowledgments.append(value)
        if len(acknowledgments) == 1000:
            env.shutdown.set()
        else:
            env.commands.put(("setExposureTime", value + 1, produce))

    def capture(**_):
        captures.append(len(acknowledgments))
        env.shutdown.set()

    env.commands.put(("setExposureTime", 1000, produce))
    monkeypatch.setattr(processor, "process_one_cycle", capture)

    env.run()

    assert len(captures) == 1, "A continuously replenished queue starved capture"
    assert 0 < captures[0] < 1000
    assert acknowledgments == list(range(1000, 1000 + len(acknowledgments)))
