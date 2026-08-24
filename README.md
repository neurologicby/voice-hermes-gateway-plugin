# Hermes VoiceGateway plugin

Открытый platform-плагин для Hermes Agent 0.20.5, добавляющий голосовой
WebSocket-канал с pairing, streaming STT/TTS, barge-in, текстом и файлами.

Фаза 0 завершена; реализуется Фаза 1 (текст, файлы, сессии). Контракты интеграции сверены с
Hermes commit `ddbd928ee4e881f0c7b3536a00355647c6559fe2`.

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
