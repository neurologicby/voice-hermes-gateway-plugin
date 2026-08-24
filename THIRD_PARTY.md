# Реестр сторонних компонентов и моделей

Статус: рабочий compliance gate. Наличие открытого исходного кода движка не
означает автоматически, что веса модели или обучающий датасет можно поставлять.

## Разрешённые компоненты

| Компонент | Назначение | Лицензия | Статус |
|---|---|---|---|
| Hermes Agent 0.20.5 | Host API, не включается в плагин | MIT | разрешён |
| aiohttp 3.14.3 | WebSocket/HTTP transport | Apache-2.0 | разрешён; совпадает с Hermes messaging extra |
| sherpa-onnx 1.13.4 | Streaming STT/KWS engine | Apache-2.0 | движок разрешён; каждую модель проверять отдельно |
| sherpa T-One Russian 2025-09-08 | Streaming RU STT weights | Apache-2.0 | разрешён; LICENSE и SHA-256 зафиксированы в manifest |
| sherpa Zipformer English 2023-06-26 int8 | Streaming EN STT weights | Apache-2.0 | разрешён; model card, LICENSE и SHA-256 зафиксированы |
| Silero VAD v5 | Server/client endpoint detection | MIT | разрешён; ONNX и LICENSE закреплены SHA-256 |
| Silero VAD | VAD ONNX | MIT | разрешён |
| Piper 1.4.2 (`piper1-gpl`) | Russian TTS engine | GPL-3.0 | разрешён для GPL-дистрибутива; plugin-local dependency |
| Kokoro 0.9.4 | English TTS engine | Apache-2.0 | разрешён; plugin-local dependency |
| en_core_web_sm 3.8.0 | English G2P model for Kokoro/Misaki | MIT | разрешён; закреплён official release URL |
| Kokoro-82M `af_heart` | English TTS model and voice | Apache-2.0 | разрешён; commit, LICENSE и artifact SHA-256 зафиксированы в manifest |
| Piper `ru_RU-dmitri-medium` | Russian voice | model repository MIT; dataset CC0 | разрешён; commit/model card/artifact SHA-256 зафиксированы в manifest |
| Piper `ru_RU-denis-medium` | Russian voice candidate | dataset CC0 | запасной кандидат; зафиксировать model artifact notice/checksum |

## Запрещённые по умолчанию

| Модель | Причина |
|---|---|
| Piper `ru_RU-irina-medium` | model card указывает dataset license `Unknown` |
| Piper `ru_RU-ruslan-medium` | dataset CC BY-NC-SA 4.0 запрещает коммерческое использование |
| sherpa KWS/STT model без собственного LICENSE/NOTICE | Лицензия движка не доказывает лицензию весов |

Downloader моделей обязан работать только с manifest allowlist: URL, версия,
SHA-256, лицензия и ссылка на сохранённый текст лицензии/NOTICE. Неизвестная
модель не скачивается автоматически.
