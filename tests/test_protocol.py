from __future__ import annotations

import json
from uuid import uuid4

import pytest

from hermes_voice_gateway.protocol import MessageType, ProtocolError, parse_control_frame


def test_valid_hello() -> None:
    message = parse_control_frame(
        json.dumps(
            {
                "type": "hello",
                "proto": 1,
                "device_id": str(uuid4()),
                "user": "Иван",
                "client": "voice-client/0.1",
            }
        )
    )
    assert message.type is MessageType.HELLO


@pytest.mark.parametrize("raw", ["[]", "not-json", b"\xff"])
def test_invalid_json_shapes_are_rejected(raw: str | bytes) -> None:
    with pytest.raises(ProtocolError):
        parse_control_frame(raw)


def test_unknown_type_has_stable_safe_code() -> None:
    with pytest.raises(ProtocolError) as captured:
        parse_control_frame('{"type":"root_shell"}')
    assert captured.value.code == "unsupported_type"


def test_path_like_file_name_is_rejected() -> None:
    with pytest.raises(ProtocolError) as captured:
        parse_control_frame('{"type":"file","name":"../secret","mime":"text/plain","size":1}')
    assert captured.value.code == "invalid_file_name"


def test_invalid_file_mime_is_rejected() -> None:
    with pytest.raises(ProtocolError) as captured:
        parse_control_frame('{"type":"file","name":"report.pdf","mime":"pdf","size":1}')
    assert captured.value.code == "invalid_mime"


def test_boolean_is_not_accepted_as_sequence() -> None:
    with pytest.raises(ProtocolError):
        parse_control_frame('{"type":"audio_end","seq":true}')
