# Hermes VoiceGateway plugin

Открытый platform-плагин для Hermes Agent 0.20.5, добавляющий голосовой
WebSocket-канал с pairing, streaming STT/TTS, barge-in, текстом и файлами.

Фазы 0–1 завершены локальными contract/E2E probes; реализуется Фаза 2
(streaming STT). Контракты интеграции сверены с
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

Для локальной sherpa-модели задаются `stt_manifest` и `stt_model_dir` в
`PlatformConfig.extra`. Manifest обязан перечислять `LICENSE`/`NOTICE` и SHA-256
каждого artifact; загрузка recognizer выполняется вне event loop.

## Лицензия

Код распространяется по GNU GPL v3 или более поздней версии. Модели имеют
собственные лицензии и включаются только после проверки model card/provenance.
