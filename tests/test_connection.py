from __future__ import annotations

import json
from uuid import uuid4

import pytest

from hermes_voice_gateway.connection import ConnectionContext, ConnectionState
from hermes_voice_gateway.protocol import ProtocolError, parse_control_frame


def test_application_message_requires_pairing() -> None:
    connection = ConnectionContext()
    with pytest.raises(ProtocolError) as captured:
        connection.authorize(parse_control_frame('{"type":"text","text":"привет"}'))
    assert captured.value.code == "pair_required"


def test_ready_connection_accepts_text() -> None:
    connection = ConnectionContext()
    device_id = str(uuid4())
    connection.mark_ready(device_id=device_id, user_name="Иван", chat_id=f"voice:{device_id}")
    connection.authorize(parse_control_frame('{"type":"text","text":"привет"}'))
    assert connection.state is ConnectionState.READY


def test_audio_sequence_rejects_stale_end() -> None:
    connection = ConnectionContext(state=ConnectionState.READY)
    connection.start_audio(7)
    with pytest.raises(ProtocolError) as captured:
        connection.finish_audio(6)
    assert captured.value.code == "stale_audio"


def test_pre_auth_hello_is_allowed() -> None:
    device_id = str(uuid4())
    raw = json.dumps(
        {
            "type": "hello",
            "proto": 1,
            "device_id": device_id,
            "user": "Иван",
            "client": "voice-client/0.1",
        }
    )
    ConnectionContext().authorize(parse_control_frame(raw))
