"""Строгая валидация управляющих кадров protocol v1."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

PROTOCOL_VERSION = 1
MAX_CONTROL_FRAME_BYTES = 64 * 1024
MAX_TEXT_CHARS = 16_384
MAX_NAME_CHARS = 128


class MessageType(StrEnum):
    PAIR_REQUEST = "pair_request"
    HELLO = "hello"
    PING = "ping"
    TEST = "test"
    TEXT = "text"
    AUDIO_START = "audio_start"
    AUDIO_END = "audio_end"
    FILE = "file"
    MUTE = "mute"
    INTERRUPT = "interrupt"
    MODE = "mode"
    WAKE = "wake"


@dataclass(frozen=True, slots=True)
class ControlMessage:
    type: MessageType
    payload: dict[str, Any]


class ProtocolError(ValueError):
    """Безопасная ошибка, которую можно преобразовать в protocol error frame."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def parse_control_frame(raw: str | bytes) -> ControlMessage:
    """Разбирает JSON-frame и проверяет инварианты, не зависящие от состояния WS."""

    encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
    if len(encoded) > MAX_CONTROL_FRAME_BYTES:
        raise ProtocolError("frame_too_large", "Управляющий кадр превышает лимит")

    try:
        decoded = encoded.decode("utf-8")
        data = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid_json", "Ожидался JSON-объект в UTF-8") from exc

    if not isinstance(data, dict):
        raise ProtocolError("invalid_message", "Корнем сообщения должен быть JSON-объект")

    raw_type = data.get("type")
    if not isinstance(raw_type, str):
        raise ProtocolError("missing_type", "Поле type обязательно")
    try:
        message_type = MessageType(raw_type)
    except ValueError as exc:
        raise ProtocolError("unsupported_type", "Тип сообщения не поддерживается") from exc

    validators = {
        MessageType.PAIR_REQUEST: _validate_pair_request,
        MessageType.HELLO: _validate_hello,
        MessageType.PING: _validate_ping,
        MessageType.TEST: _validate_no_fields,
        MessageType.TEXT: _validate_text,
        MessageType.AUDIO_START: _validate_audio_start,
        MessageType.AUDIO_END: _validate_audio_end,
        MessageType.FILE: _validate_file,
        MessageType.MUTE: _validate_mute,
        MessageType.INTERRUPT: _validate_no_fields,
        MessageType.MODE: _validate_mode,
        MessageType.WAKE: _validate_wake,
    }
    validators[message_type](data)
    return ControlMessage(message_type, data)


def _required_string(data: dict[str, Any], field: str, *, max_chars: int) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError("invalid_field", f"Поле {field} должно быть непустой строкой")
    if len(value) > max_chars:
        raise ProtocolError("invalid_field", f"Поле {field} превышает лимит")
    return value


def _positive_int(data: dict[str, Any], field: str) -> int:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProtocolError("invalid_field", f"Поле {field} должно быть положительным целым")
    return value


def _validate_device_id(value: str) -> None:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ProtocolError("invalid_device_id", "device_id должен быть UUID") from exc
    if parsed.int == 0:
        raise ProtocolError("invalid_device_id", "Нулевой device_id запрещён")


def _validate_pair_request(data: dict[str, Any]) -> None:
    _validate_device_id(_required_string(data, "device_id", max_chars=36))
    _required_string(data, "user_name", max_chars=MAX_NAME_CHARS)


def _validate_hello(data: dict[str, Any]) -> None:
    if data.get("proto") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported_protocol", "Поддерживается protocol v1")
    _validate_device_id(_required_string(data, "device_id", max_chars=36))
    _required_string(data, "user", max_chars=MAX_NAME_CHARS)
    _required_string(data, "client", max_chars=MAX_NAME_CHARS)


def _validate_ping(data: dict[str, Any]) -> None:
    value = data.get("t")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProtocolError("invalid_field", "Поле t должно быть целым Unix timestamp")


def _validate_no_fields(data: dict[str, Any]) -> None:
    del data


def _validate_text(data: dict[str, Any]) -> None:
    _required_string(data, "text", max_chars=MAX_TEXT_CHARS)


def _validate_audio_start(data: dict[str, Any]) -> None:
    _positive_int(data, "seq")
    if data.get("lang") not in {"auto", "ru", "en"}:
        raise ProtocolError("invalid_field", "lang должен быть auto, ru или en")


def _validate_audio_end(data: dict[str, Any]) -> None:
    _positive_int(data, "seq")


def _validate_file(data: dict[str, Any]) -> None:
    name = _required_string(data, "name", max_chars=255)
    if "\x00" in name or "/" in name or "\\" in name or name in {".", ".."}:
        raise ProtocolError("invalid_file_name", "Имя файла содержит запрещённые символы")
    _required_string(data, "mime", max_chars=255)
    _positive_int(data, "size")


def _validate_mute(data: dict[str, Any]) -> None:
    if not isinstance(data.get("on"), bool):
        raise ProtocolError("invalid_field", "Поле on должно быть boolean")


def _validate_mode(data: dict[str, Any]) -> None:
    if data.get("mode") not in {"voice_only", "all", "off"}:
        raise ProtocolError("invalid_field", "Неизвестный режим")


def _validate_wake(data: dict[str, Any]) -> None:
    _required_string(data, "phrase", max_chars=MAX_NAME_CHARS)
    if data.get("engine") not in {"sherpa", "openwakeword"}:
        raise ProtocolError("invalid_field", "Неизвестный wake-word движок")
