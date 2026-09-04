import json
from unittest.mock import Mock

import pytest
from paho.mqtt.client import MQTTMessage
from segdete.config.messaging import MessagingConfig
from segdete.mqtt.tb_client import TBEdgeClient
from tb_device_mqtt import ATTRIBUTES_TOPIC, TBDeviceMqttClient


@pytest.fixture
def mqtt_commands(processing_env, monkeypatch):
    env = processing_env
    monkeypatch.setenv("MQTT_TOKEN", "test-device")
    monkeypatch.setattr(TBDeviceMqttClient, "connect", Mock())
    publish = Mock()
    monkeypatch.setattr(TBDeviceMqttClient, "_publish_data", publish)
    client = TBEdgeClient(MessagingConfig(), env.commands)
    client.connect()
    publish.reset_mock()
    try:

        def receive(payload):
            message = MQTTMessage()
            message.topic = ATTRIBUTES_TOPIC.encode()
            message.payload = json.dumps(payload).encode()
            client.client._on_message(None, None, message)
            env.commands.put(("setIntervalSec", 10, lambda _: env.shutdown.set()))
            env.run()
            return [call.args[0] for call in publish.call_args_list]

        yield receive
    finally:
        client.client.stop()


def test_attribute_batch_dispatches_each_command_once(mqtt_commands, processing_env):
    responses = mqtt_commands(
        {
            "setSystemRunning": False,
            "setIntervalSec": 30,
            "setExposureTime": 1000,
        }
    )

    assert responses == [
        {"systemRunning": False},
        {"intervalSec": 30},
        {"exposureTime": 1000},
    ]
    processing_env.camera.stop.assert_called_once_with()
    assert processing_env.camera.set_exp.call_count == 2


def test_invalid_and_unknown_attributes_have_no_success_response(mqtt_commands):
    assert mqtt_commands({"setIntervalSec": -1, "unsupportedAttribute": 1}) == []


def test_failed_device_command_has_no_success_response(mqtt_commands, processing_env):
    processing_env.camera.set_exp.return_value = False

    assert mqtt_commands({"setExposureTime": 1000}) == []


def test_disconnect_is_noop_before_connection(monkeypatch):
    monkeypatch.setenv("MQTT_TOKEN", "test-device")
    raw_client = Mock()
    raw_client.is_connected.return_value = False
    monkeypatch.setattr(TBEdgeClient, "_create_tb_client", lambda _: raw_client)
    client = TBEdgeClient(MessagingConfig(), Mock())

    assert client.disconnect() is False
    raw_client.disconnect.assert_not_called()


def test_disconnect_closes_connected_client(monkeypatch):
    monkeypatch.setenv("MQTT_TOKEN", "test-device")
    raw_client = Mock()
    raw_client.is_connected.return_value = True
    monkeypatch.setattr(TBEdgeClient, "_create_tb_client", lambda _: raw_client)
    client = TBEdgeClient(MessagingConfig(), Mock())

    assert client.disconnect() is True
    raw_client.disconnect.assert_called_once_with()


def test_disconnect_closes_connection_before_async_callback(monkeypatch):
    monkeypatch.setenv("MQTT_TOKEN", "test-device")
    raw_client = Mock()
    raw_client.is_connected.return_value = False
    monkeypatch.setattr(TBEdgeClient, "_create_tb_client", lambda _: raw_client)
    client = TBEdgeClient(MessagingConfig(), Mock())
    client._connect_started = True

    assert client.disconnect() is True
    raw_client.disconnect.assert_called_once_with()
