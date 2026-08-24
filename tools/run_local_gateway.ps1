$ErrorActionPreference = "Stop"

$hermesTool = Join-Path $env:APPDATA "uv\tools\hermes-agent"
$hermesExe = Join-Path $env:USERPROFILE ".local\bin\hermes.exe"

if (-not (Test-Path -LiteralPath $hermesExe)) {
    throw "Hermes CLI not found: $hermesExe"
}
if (-not (Test-Path -LiteralPath $hermesTool)) {
    throw "Hermes uv-tool environment not found: $hermesTool"
}

# The editable Windows Hermes checkout also has a legacy Python 3.11 venv.
# Pin gateway imports to the active uv-tool Python 3.12 environment so binary
# plugin dependencies are loaded from the plugin-local deps directory.
$env:VIRTUAL_ENV = $hermesTool

& $hermesExe gateway run
exit $LASTEXITCODE
