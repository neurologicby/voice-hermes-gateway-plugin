# Local STT/TTS model bundles

Веса не включаются в репозиторий автоматически. Каталог модели должен содержать
JSON-manifest, все перечисленные в нём artifacts и `LICENSE`/`NOTICE`. Перед
инициализацией движка плагин проверяет allowlist SPDX-лицензий, безопасные пути и
SHA-256 каждого файла.

Первый кандидат для ручной лицензионной проверки — официальный streaming T-One
Russian bundle sherpa-onnx. Его нельзя добавлять в каталог поставки, пока SPDX,
source URL и контрольные суммы конкретного архива не зафиксированы в manifest.

Piper `ru_RU-dmitri-medium` разрешён для локальной установки: repository metadata
указывает MIT, dataset — CC0, а конкретный Hugging Face commit и SHA-256 закреплены в
`model_manifests/piper-ru_RU-dmitri-medium.json`. Сами веса остаются ignored и не
попадают в Git.
