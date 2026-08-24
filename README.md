# Hermes VoiceGateway plugin

Открытый platform-плагин для Hermes Agent 0.19.1, добавляющий голосовой
WebSocket-канал с pairing, streaming STT/TTS, barge-in, текстом и файлами.

Проект находится в ранней Фазе 0. Контракты интеграции сверяются с локальным
Hermes commit `f3cda0ceb18d8ba7465a6d223098ef0e56c8fee1`.

## Разработка

Из корня PyCharm workspace:

```powershell
.venv\Scripts\python.exe -m pytest plugin\tests -q
.venv\Scripts\ruff.exe check plugin
C:\Users\user\AppData\Roaming\uv\tools\hermes-agent\Scripts\python.exe `
  plugin\tools\pairing_e2e_probe.py
```

Runtime-зависимости целевой установки Hermes не модифицируются. Дополнительные
ML-зависимости и модели устанавливаются локально в deploy-каталог плагина.

## Лицензия

Код распространяется по GNU GPL v3 или более поздней версии. Модели имеют
собственные лицензии и включаются только после проверки model card/provenance.
