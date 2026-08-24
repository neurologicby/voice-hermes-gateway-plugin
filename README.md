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

Проверенный русский bundle описан в
`model_manifests/sherpa-t-one-ru-2025-09-08.json`. Он использует Apache-2.0,
принимает потоковые 8 кГц features (вход protocol v1 остаётся 16 кГц) и не
коммитится вместе с весами. Локальный smoke-test запускается так:

```powershell
.venv\Scripts\python.exe plugin\tools\stt_audio_probe.py <record.wav> `
  --manifest plugin\model_manifests\sherpa-t-one-ru-2025-09-08.json `
  --model-dir plugin\models\sherpa-onnx-streaming-t-one-russian-2025-09-08 `
  --language ru
```

Английский int8 Zipformer описан в
`model_manifests/sherpa-zipformer-en-2023-06-26-int8.json`, Silero VAD — в
`model_manifests/silero-vad-v5.json`. Для двуязычного сервера основной RU bundle
задаётся через `stt_manifest`/`stt_model_dir`, английский — через
`stt_en_manifest`/`stt_en_model_dir`. Клиент обязан явно передавать `lang:ru` или
`lang:en`; автоматическое определение не используется. VAD задаётся через
`vad_manifest`/`vad_model_dir` и по умолчанию предлагает endpoint после 600 мс тишины.

## Лицензия

Код распространяется по GNU GPL v3 или более поздней версии. Модели имеют
собственные лицензии и включаются только после проверки model card/provenance.
