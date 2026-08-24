from __future__ import annotations

import json
from uuid import uuid4

import pytest

from hermes_voice_gateway.connection import (
    AUDIO_SEQUENCE_BYTES,
    ConnectionContext,
    ConnectionState,
)
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


def test_audio_chunk_contains_sequence_header_and_even_pcm() -> None:
    connection = ConnectionContext(state=ConnectionState.READY)
    connection.start_audio(7)
    seq, pcm = connection.parse_audio_chunk((7).to_bytes(AUDIO_SEQUENCE_BYTES, "big") + b"\x01\x00")
    assert seq == 7
    assert pcm == b"\x01\x00"


def test_audio_chunk_rejects_stale_header() -> None:
    connection = ConnectionContext(state=ConnectionState.READY)
    connection.start_audio(7)
    with pytest.raises(ProtocolError) as captured:
        connection.parse_audio_chunk((6).to_bytes(AUDIO_SEQUENCE_BYTES, "big") + b"\x01\x00")
    assert captured.value.code == "stale_audio"


def test_audio_chunk_rejects_odd_pcm_size() -> None:
    connection = ConnectionContext(state=ConnectionState.READY)
    connection.start_audio(7)
    with pytest.raises(ProtocolError) as captured:
        connection.parse_audio_chunk((7).to_bytes(AUDIO_SEQUENCE_BYTES, "big") + b"\x01")
    assert captured.value.code == "invalid_audio_chunk"


def test_audio_and_file_payloads_are_mutually_exclusive() -> None:
    connection = ConnectionContext(state=ConnectionState.READY)
    connection.start_file(name="report.txt", mime="text/plain", size=5, max_bytes=10)
    with pytest.raises(ProtocolError) as captured:
        connection.start_audio(1)
    assert captured.value.code == "file_in_progress"


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


def test_file_chunks_complete_only_at_declared_size() -> None:
    connection = ConnectionContext(state=ConnectionState.READY)
    connection.start_file(name="report.txt", mime="text/plain", size=5, max_bytes=10)
    assert connection.append_file_chunk(b"he") is None
    completed = connection.append_file_chunk(b"llo")
    assert completed is not None
    assert completed.name == "report.txt"
    assert completed.mime == "text/plain"
    assert completed.data == b"hello"
    assert connection.pending_file is None


def test_file_overflow_cancels_pending_upload() -> None:
    connection = ConnectionContext(state=ConnectionState.READY)
    connection.start_file(name="report.txt", mime="text/plain", size=2, max_bytes=10)
    with pytest.raises(ProtocolError) as captured:
        connection.append_file_chunk(b"too long")
    assert captured.value.code == "file_size_mismatch"
    assert connection.pending_file is None


def test_interrupt_cancels_pending_file() -> None:
    connection = ConnectionContext(state=ConnectionState.READY)
    connection.start_file(name="report.txt", mime="text/plain", size=5, max_bytes=10)
    connection.interrupt()
    assert connection.pending_file is None


def test_oversized_file_is_rejected_before_binary_payload() -> None:
    connection = ConnectionContext(state=ConnectionState.READY)
    with pytest.raises(ProtocolError) as captured:
        connection.start_file(
            name="large.bin",
            mime="application/octet-stream",
            size=11,
            max_bytes=10,
        )
    assert captured.value.code == "file_too_large"
