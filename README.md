# Hermes VoiceGateway plugin

Открытый platform-плагин для Hermes Agent, добавляющий голосовой
WebSocket-канал с pairing, streaming STT/TTS, barge-in, текстом и файлами.

Контракты и полный локальный голосовой тракт проверены с Hermes Agent 0.19.1,
commit `f3cda0ceb18d8ba7465a6d223098ef0e56c8fee1`. Production-код Hermes при этом
не изменяется: плагин подключается только через публичные platform/TTS hooks.

## Разработка

Из корня PyCharm workspace:

```powershell
.venv\Scripts\python.exe -m pytest plugin\tests -q
.venv\Scripts\ruff.exe check plugin
C:\Users\user\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe `
  plugin\tools\pairing_e2e_probe.py
```

Локальный Hermes gateway с уже настроенными моделями запускается из корня
workspace одной командой:

```powershell
.\plugin\tools\run_local_gateway.ps1
```

Скрипт сохраняет pairing и конфигурацию Hermes и задаёт корректное uv-tool
окружение для бинарных plugin-local зависимостей на Windows.

Полный русский E2E использует настоящий `VoiceWSClient`, pairing store и
dispatcher Hermes, VoiceGateway WebSocket, Silero VAD, T-One STT и Piper TTS.
Контрольный ответ сохраняется в `plugin/build/full-stack-ru-e2e.wav`:

```powershell
C:\Users\user\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe `
  plugin\tools\full_stack_ru_e2e.py
```

LLM в этом probe заменён детерминированным message handler: локальный аудиотракт
проверяется без внешней сети, ключей API и платных запросов. Сам dispatch проходит
через фактический `BasePlatformAdapter` установленного Hermes.

Runtime-зависимости целевой установки Hermes не модифицируются. Дополнительные
ML-зависимости и модели устанавливаются локально в deploy-каталог плагина.

## Установка из GitHub

После публикации отдельного репозитория плагин устанавливается штатным менеджером
Hermes без правок ядра:

```powershell
hermes plugins install OWNER/hermes-voice-gateway --enable
```

Репозиторий пока не имеет настроенного GitHub remote, поэтому `OWNER` будет заменён
после выбора организации или аккаунта. GitHub workflow проверяет unit-тесты и
контракт с актуальным `nousresearch/hermes-agent` при каждом push/PR.

ML-веса не коммитятся в Git. Публичному релизу потребуется отдельный checksum-verified
bootstrap для установки зависимостей в `deps/` и загрузки выбранных RU/EN model
bundles в `models/`. До появления этого bootstrap простой `plugins install` ставит
код и регистрирует плагин, но ещё не подготавливает STT/TTS runtime автоматически.

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

Русский streaming TTS использует `piper-tts==1.4.2` и зарегистрирован в штатном
реестре Hermes под именем `voice_piper`. Движок загружается лениво в worker thread,
а PCM голоса 22,05 кГц преобразуется в protocol v1 PCM 24 кГц. Пример Hermes config:

```yaml
tts:
  streaming:
    provider: voice_piper
  voice_piper:
    manifest: C:/path/to/plugin/model_manifests/piper-ru_RU-dmitri-medium.json
    model_dir: C:/path/to/plugin/models/piper-ru_RU-dmitri-medium
    chunk_ms: 100
```

English streaming TTS использует Apache-2.0 Kokoro 82M с голосом `af_heart` и
регистрируется как `voice_kokoro`. Provider работает полностью офлайн: manifest
обязан закрепить SHA-256 для `kokoro-v1_0.pth`, `config.json`, `af_heart.pt` и
`LICENSE`; автоматические загрузки модели во время запуска запрещены. В voice extra
также закреплена `en-core-web-sm==3.8.0`, необходимая для английского G2P. Готовый
manifest находится в `model_manifests/kokoro-en-af-heart.json`, локальный bundle —
в игнорируемом Git каталоге `models/kokoro-en-af-heart`.

```yaml
tts:
  streaming:
    provider: voice_kokoro
  voice_kokoro:
    manifest: C:/path/to/plugin/model_manifests/kokoro-en-af-heart.json
    model_dir: C:/path/to/plugin/models/kokoro-en-af-heart
    speed: 1.0
    chunk_ms: 100
```

Реальный офлайн probe сохраняет результат в WAV и печатает холодную загрузку,
время синтеза и длительность аудио:

```powershell
python tools/tts_audio_probe.py `
  model_manifests/kokoro-en-af-heart.json `
  models/kokoro-en-af-heart `
  build/kokoro-en-e2e.wav
```

Для обычной работы с переключателем клиента используйте `voice_explicit`. Язык
берётся только из `audio_start.lang`; анализ текста и автоматическое определение
языка не выполняются. Контекст изолирован для каждого параллельного voice turn.

```yaml
tts:
  streaming:
    provider: voice_explicit
  voice_explicit:
    ru:
      manifest: /opt/hermes/models/piper-ru/manifest.json
      model_dir: /opt/hermes/models/piper-ru
    en:
      manifest: /opt/hermes/models/kokoro-en/manifest.json
      model_dir: /opt/hermes/models/kokoro-en
      speed: 1.0
```

Manifest закрепляет MIT metadata репозитория, commit, model card и SHA-256
`ru_RU-dmitri-medium`; dataset помечен CC0. Язык не определяется автоматически:
RU/EN выбирается клиентом явно.

## Лицензия

Код распространяется по GNU GPL v3 или более поздней версии. Модели имеют
собственные лицензии и включаются только после проверки model card/provenance.
