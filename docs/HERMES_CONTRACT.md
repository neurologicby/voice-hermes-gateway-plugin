# Контракт с Hermes Agent 0.19.1

Baseline: `f3cda0ceb18d8ba7465a6d223098ef0e56c8fee1`, 2026-07-31.
Source: `%LOCALAPPDATA%/hermes/hermes-agent` (только чтение).

## Подтверждённые сигнатуры

- `ctx.register_platform(name, label, adapter_factory, check_fn, validate_config=None,
  required_env=None, install_hint="", **PlatformEntry fields)`.
- Обязательные методы `BasePlatformAdapter`: `connect`, `disconnect`, `send`,
  `get_chat_info`.
- `send(chat_id, content, reply_to=None, metadata=None) -> SendResult`.
- `send_voice(chat_id, audio_path, caption=None, reply_to=None, metadata=None, **kwargs)`.
- Streaming TTS opt-in требует `supports_streaming_tts(chat_id, audio_format)`.
- Lifecycle streaming TTS: `begin` → `write*` → `finish(interrupted=False)` либо
  idempotent `abort(error=None)`.
- `PairingStore.generate_code/is_approved/revoke/list_pending/approve_code` соответствуют
  port интерфейсу плагина.
- `Platform("voice")` создаётся динамически после регистрации plugin platform.

## Расхождения с документацией проекта

1. В документах `send` принимает произвольный `text/**kwargs`; живой API требует
   `content/reply_to/metadata` и возвращает `SendResult`.
2. Документированный `send_voice(bytes, duration)` неверен; живой API принимает путь.
3. В streaming контракте добавлены обязательные для opt-in методы
   `supports_streaming_tts` и `finish_streaming_tts`.
4. `begin_streaming_tts` принимает обязательный `AudioFormat` и может вернуть `None`.
5. `ensure_deps_fn` отсутствует в `PlatformEntry` и передавать его через
   `register_platform` нельзя. Установка ML deps реализуется внутри плагина без этого hook.
6. `allow_all_env` существует и должен регистрироваться вместе с `allowed_users_env`.

Проверка: `tools/hermes_contract_probe.py` импортирует адаптер против source baseline,
проверяет отсутствие abstract methods, dynamic Platform и маршруты transport app.

