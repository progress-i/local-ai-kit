# 4. Голос

CPU: AVX2, FMA и F16C. Остановите запущенный проект через `Ctrl+C`.

## Ubuntu

### 1. Открыть папку программы и задать кэш проекта

```bash
cd "$HOME/local-ai-kit/app"
export TMPDIR="$HOME/LocalAISeries/tmp"
export XDG_CACHE_HOME="$HOME/LocalAISeries/cache/xdg"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME"
```

### 2. Установить Piper и библиотеки голоса

Piper озвучивает текст. Файл `locks/voice-linux.txt` для Ubuntu или `locks/voice-windows.txt` для Windows содержит закреплённые версии и SHA-256 библиотек.

```bash
"$HOME/LocalAISeries/env/bin/python" -m pip --isolated install --require-hashes --only-binary=:all: --no-input --disable-pip-version-check --cache-dir "$HOME/LocalAISeries/cache/pip" -r "$HOME/local-ai-kit/locks/voice-linux.txt" &&
"$HOME/LocalAISeries/env/bin/python" -m pip --isolated check
```

### 3. Скачать и распаковать исходники Whisper.cpp 1.9.5

Whisper.cpp распознаёт речь. Исходники сохраняются в `LocalAISeries/src/whisper.cpp`.

```bash
mkdir -p "$(dirname "$HOME/LocalAISeries/cache/downloads/whisper-source.download")"
if [ ! -f "$HOME/LocalAISeries/cache/downloads/whisper-source.download" ]; then
  "$HOME/LocalAISeries/env/bin/python" -B -c 'from pathlib import Path; from urllib.request import urlretrieve; urlretrieve("https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/refs/tags/v1.9.5", Path.home() / "LocalAISeries/cache/downloads/whisper-source.download.part")'
  printf '%s  %s\n' 'ff1a9053feb509ff9d7729703355541ae9690073a6b1c40eb692c962e0dc1720' "$HOME/LocalAISeries/cache/downloads/whisper-source.download.part" | sha256sum --check - &&
  mv "$HOME/LocalAISeries/cache/downloads/whisper-source.download.part" "$HOME/LocalAISeries/cache/downloads/whisper-source.download"
else
  printf '%s  %s\n' 'ff1a9053feb509ff9d7729703355541ae9690073a6b1c40eb692c962e0dc1720' "$HOME/LocalAISeries/cache/downloads/whisper-source.download" | sha256sum --check -
fi
```

```bash
mkdir -p "$HOME/LocalAISeries/src/whisper.cpp"
tar -xf "$HOME/LocalAISeries/cache/downloads/whisper-source.download" -C "$HOME/LocalAISeries/src/whisper.cpp" --strip-components=1 &&
printf '%s' 'ff1a9053feb509ff9d7729703355541ae9690073a6b1c40eb692c962e0dc1720' > "$HOME/LocalAISeries/src/whisper.cpp/.local-ai-source-sha256"
```

### 4. Собрать whisper-cli для распознавания речи

Программа появится в `LocalAISeries/build/whisper/bin`.

```bash
AiCmake="$HOME/LocalAISeries/env/bin/cmake"
"$AiCmake" -S "$HOME/LocalAISeries/src/whisper.cpp" -B "$HOME/LocalAISeries/build/whisper" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DWHISPER_BUILD_TESTS=OFF \
  -DWHISPER_CURL=OFF \
  -DGGML_CUDA=OFF \
  -DGGML_VULKAN=OFF \
  -DGGML_NATIVE=OFF \
  -DGGML_AVX=ON \
  -DGGML_AVX2=ON \
  -DGGML_FMA=ON \
  -DGGML_F16C=ON &&
"$AiCmake" --build "$HOME/LocalAISeries/build/whisper" --config Release --parallel 1 --target whisper-cli
```

`GGML_AVX2`, `GGML_FMA`, `GGML_F16C` включают инструкции CPU; `--target whisper-cli` собирает распознавание речи.

### 5. Скачать модели речи и сохранить учёт установки

`ggml-base.bin` распознаёт речь. ONNX-файл и JSON-конфигурация задают русский голос Piper. `denis-MODEL_CARD.txt` содержит сведения о голосе. Файлы сохраняются в `LocalAISeries/models` и проверяются по SHA-256.

```bash
mkdir -p "$(dirname "$HOME/LocalAISeries/models/ggml-base.bin")"
if [ ! -f "$HOME/LocalAISeries/models/ggml-base.bin" ]; then
  "$HOME/LocalAISeries/env/bin/python" -B -c 'from pathlib import Path; from urllib.request import urlretrieve; urlretrieve("https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-base.bin", Path.home() / "LocalAISeries/models/ggml-base.bin.part")'
  printf '%s  %s\n' '60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe' "$HOME/LocalAISeries/models/ggml-base.bin.part" | sha256sum --check - &&
  mv "$HOME/LocalAISeries/models/ggml-base.bin.part" "$HOME/LocalAISeries/models/ggml-base.bin"
else
  printf '%s  %s\n' '60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe' "$HOME/LocalAISeries/models/ggml-base.bin" | sha256sum --check -
fi
```

```bash
mkdir -p "$(dirname "$HOME/LocalAISeries/models/ru_RU-denis-medium.onnx")"
if [ ! -f "$HOME/LocalAISeries/models/ru_RU-denis-medium.onnx" ]; then
  "$HOME/LocalAISeries/env/bin/python" -B -c 'from pathlib import Path; from urllib.request import urlretrieve; urlretrieve("https://huggingface.co/rhasspy/piper-voices/resolve/c10ece1aade47bb51c153c893d14e5bf8e5b7117/ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx", Path.home() / "LocalAISeries/models/ru_RU-denis-medium.onnx.part")'
  printf '%s  %s\n' '15fab56e11a097858ee115545d0f697fc2a316c41a291a5362349fb870411b0a' "$HOME/LocalAISeries/models/ru_RU-denis-medium.onnx.part" | sha256sum --check - &&
  mv "$HOME/LocalAISeries/models/ru_RU-denis-medium.onnx.part" "$HOME/LocalAISeries/models/ru_RU-denis-medium.onnx"
else
  printf '%s  %s\n' '15fab56e11a097858ee115545d0f697fc2a316c41a291a5362349fb870411b0a' "$HOME/LocalAISeries/models/ru_RU-denis-medium.onnx" | sha256sum --check -
fi
```

```bash
mkdir -p "$(dirname "$HOME/LocalAISeries/models/ru_RU-denis-medium.onnx.json")"
if [ ! -f "$HOME/LocalAISeries/models/ru_RU-denis-medium.onnx.json" ]; then
  "$HOME/LocalAISeries/env/bin/python" -B -c 'from pathlib import Path; from urllib.request import urlretrieve; urlretrieve("https://huggingface.co/rhasspy/piper-voices/resolve/c10ece1aade47bb51c153c893d14e5bf8e5b7117/ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx.json", Path.home() / "LocalAISeries/models/ru_RU-denis-medium.onnx.json.part")'
  printf '%s  %s\n' '831c860dac0b5073eaa81610a0a638ec23d90a6cf8e5f871b4485c2cec3767c8' "$HOME/LocalAISeries/models/ru_RU-denis-medium.onnx.json.part" | sha256sum --check - &&
  mv "$HOME/LocalAISeries/models/ru_RU-denis-medium.onnx.json.part" "$HOME/LocalAISeries/models/ru_RU-denis-medium.onnx.json"
else
  printf '%s  %s\n' '831c860dac0b5073eaa81610a0a638ec23d90a6cf8e5f871b4485c2cec3767c8' "$HOME/LocalAISeries/models/ru_RU-denis-medium.onnx.json" | sha256sum --check -
fi
```

```bash
mkdir -p "$(dirname "$HOME/LocalAISeries/models/denis-MODEL_CARD.txt")"
if [ ! -f "$HOME/LocalAISeries/models/denis-MODEL_CARD.txt" ]; then
  "$HOME/LocalAISeries/env/bin/python" -B -c 'from pathlib import Path; from urllib.request import urlretrieve; urlretrieve("https://huggingface.co/rhasspy/piper-voices/resolve/c10ece1aade47bb51c153c893d14e5bf8e5b7117/ru/ru_RU/denis/medium/MODEL_CARD", Path.home() / "LocalAISeries/models/denis-MODEL_CARD.txt.part")'
  printf '%s  %s\n' '8b5d685dd80f8ad3f8dbbe1c56b16bb0809f00c144af3642dbcf3b707eb89c12' "$HOME/LocalAISeries/models/denis-MODEL_CARD.txt.part" | sha256sum --check - &&
  mv "$HOME/LocalAISeries/models/denis-MODEL_CARD.txt.part" "$HOME/LocalAISeries/models/denis-MODEL_CARD.txt"
else
  printf '%s  %s\n' '8b5d685dd80f8ad3f8dbbe1c56b16bb0809f00c144af3642dbcf3b707eb89c12' "$HOME/LocalAISeries/models/denis-MODEL_CARD.txt" | sha256sum --check -
fi
```

Записать сборку, модели и библиотеки в учёт установки.

```bash
"$HOME/LocalAISeries/env/bin/python" -B - <<'PY'
from pathlib import Path
from lib.common import owned_root
root = owned_root(Path.home() / 'LocalAISeries')
from lib.common import LOCK
from manage import read_state, installed_packages, whisper_binary
assert whisper_binary(root).is_file()
state = read_state(root)
state['artifacts']['whisper-source'] = {**LOCK['artifacts']['whisper-source'], 'status': 'verified', 'path': str(root / 'cache/downloads/whisper-source.download')}
for key, name in [('whisper-model', 'ggml-base.bin'), ('piper-model', 'ru_RU-denis-medium.onnx'), ('piper-config', 'ru_RU-denis-medium.onnx.json'), ('piper-card', 'denis-MODEL_CARD.txt')]:
    state['artifacts'][key] = {**LOCK['artifacts'][key], 'status': 'verified', 'path': str(root / 'models' / name)}
(root / 'build/whisper/.complete').write_text(LOCK['whisper_commit'])
state['programs']['whisper.cpp'] = {'version': LOCK['whisper_version'], 'commit': LOCK['whisper_commit'], 'ownership': 'built from source'}
state['stage'] = max(state['stage'], 4)
installed_packages(root, state)
print('STAGE 4: OK')
PY
```

### 6. Запустить помощника на CPU

Команда запуска использует установленные файлы из `LocalAISeries`.

```bash
bash "$HOME/local-ai-kit/local-ai.sh" start --stage 4
```

## Windows

### Перед установкой на Windows 11
Smart App Control появился в Windows 11. Он проверяет подписи и репутацию программ и может блокировать компоненты проекта.
При блокировке: Безопасность Windows → Управление приложениями и браузером → Параметры интеллектуального управления приложениями → Выкл.
Другие компоненты безопасности не меняются.

### 1. Открыть PowerShell и задать кэш проекта

```powershell
Set-Location "$HOME/local-ai-kit/app"
$ErrorActionPreference = 'Stop'
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
$env:TEMP = "$HOME/LocalAISeries/tmp"
$env:TMP = $env:TEMP
$env:XDG_CACHE_HOME = "$HOME/LocalAISeries/cache/xdg"
$env:PYTHONDONTWRITEBYTECODE = '1'
New-Item -ItemType Directory $env:TEMP, $env:XDG_CACHE_HOME -Force | Out-Null
```

### 2. Установить Piper и библиотеки голоса

Piper озвучивает текст. Файл `locks/voice-linux.txt` для Ubuntu или `locks/voice-windows.txt` для Windows содержит закреплённые версии и SHA-256 библиотек.

```powershell
& "$HOME/LocalAISeries/env/Scripts/python.exe" -m pip --isolated install --require-hashes '--only-binary=:all:' --no-input --disable-pip-version-check --cache-dir "$HOME/LocalAISeries/cache/pip" -r "$HOME/local-ai-kit/locks/voice-windows.txt"
if ($LASTEXITCODE) { throw 'pip: установка не завершена' }
& "$HOME/LocalAISeries/env/Scripts/python.exe" -m pip --isolated check
if ($LASTEXITCODE) { throw 'pip: зависимости несовместимы' }
```

### 3. Скачать и распаковать исходники Whisper.cpp 1.9.5

Whisper.cpp распознаёт речь. Исходники сохраняются в `LocalAISeries/src/whisper.cpp`.

```powershell
$File = "$HOME/LocalAISeries/cache/downloads/whisper-source.download"
New-Item -ItemType Directory (Split-Path $File -Parent) -Force | Out-Null
if (-not (Test-Path -LiteralPath $File)) {
    Invoke-WebRequest -UseBasicParsing -Uri 'https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/refs/tags/v1.9.5' -OutFile "$File.part"
    if ((Get-FileHash "$File.part" -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'ff1a9053feb509ff9d7729703355541ae9690073a6b1c40eb692c962e0dc1720') { throw 'SHA-256 не совпал' }
    Move-Item -LiteralPath "$File.part" -Destination $File
} elseif ((Get-FileHash $File -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'ff1a9053feb509ff9d7729703355541ae9690073a6b1c40eb692c962e0dc1720') { throw 'SHA-256 не совпал' }
```

```powershell
New-Item -ItemType Directory "$HOME/LocalAISeries/src/whisper.cpp" -Force | Out-Null
tar.exe -xf "$HOME/LocalAISeries/cache/downloads/whisper-source.download" -C "$HOME/LocalAISeries/src/whisper.cpp" '--strip-components=1'
if ($LASTEXITCODE) { throw 'Ошибка распаковки' }
[IO.File]::WriteAllText("$HOME/LocalAISeries/src/whisper.cpp/.local-ai-source-sha256", 'ff1a9053feb509ff9d7729703355541ae9690073a6b1c40eb692c962e0dc1720')
```

### 4. Собрать whisper-cli для распознавания речи

Программа появится в `LocalAISeries/build/whisper/bin`.

```powershell
$AiTools = Join-Path "$HOME/LocalAISeries" 'tools/w64devkit/bin'
$AiCmake = Join-Path $AiTools 'cmake.exe'
$env:PATH = "$AiTools;$(Join-Path "$HOME/LocalAISeries" 'python');$env:PATH"
& $AiCmake -S "$HOME/LocalAISeries/src/whisper.cpp" -B "$HOME/LocalAISeries/build/whisper" `
  '-DCMAKE_BUILD_TYPE=Release' `
  '-DBUILD_SHARED_LIBS=OFF' `
  '-DWHISPER_BUILD_TESTS=OFF' `
  '-DWHISPER_CURL=OFF' `
  '-DGGML_CUDA=OFF' `
  '-DGGML_VULKAN=OFF' `
  '-DGGML_NATIVE=OFF' `
  '-DGGML_AVX=ON' `
  '-DGGML_AVX2=ON' `
  '-DGGML_FMA=ON' `
  '-DGGML_F16C=ON' `
  -G Ninja "-DCMAKE_C_COMPILER=$AiTools/gcc.exe" "-DCMAKE_CXX_COMPILER=$AiTools/g++.exe" "-DCMAKE_MAKE_PROGRAM=$AiTools/ninja.exe"
if ($LASTEXITCODE) { throw 'CMake: настройка не завершена' }
& $AiCmake --build "$HOME/LocalAISeries/build/whisper" --config Release --parallel 1 --target whisper-cli
if ($LASTEXITCODE) { throw 'CMake: сборка не завершена' }
```

`GGML_AVX2`, `GGML_FMA`, `GGML_F16C` включают инструкции CPU; `--target whisper-cli` собирает распознавание речи.

### 5. Скачать модели речи и сохранить учёт установки

`ggml-base.bin` распознаёт речь. ONNX-файл и JSON-конфигурация задают русский голос Piper. `denis-MODEL_CARD.txt` содержит сведения о голосе. Файлы сохраняются в `LocalAISeries/models` и проверяются по SHA-256.

```powershell
$File = "$HOME/LocalAISeries/models/ggml-base.bin"
New-Item -ItemType Directory (Split-Path $File -Parent) -Force | Out-Null
if (-not (Test-Path -LiteralPath $File)) {
    Invoke-WebRequest -UseBasicParsing -Uri 'https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-base.bin' -OutFile "$File.part"
    if ((Get-FileHash "$File.part" -Algorithm SHA256).Hash.ToLowerInvariant() -ne '60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe') { throw 'SHA-256 не совпал' }
    Move-Item -LiteralPath "$File.part" -Destination $File
} elseif ((Get-FileHash $File -Algorithm SHA256).Hash.ToLowerInvariant() -ne '60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe') { throw 'SHA-256 не совпал' }
```

```powershell
$File = "$HOME/LocalAISeries/models/ru_RU-denis-medium.onnx"
New-Item -ItemType Directory (Split-Path $File -Parent) -Force | Out-Null
if (-not (Test-Path -LiteralPath $File)) {
    Invoke-WebRequest -UseBasicParsing -Uri 'https://huggingface.co/rhasspy/piper-voices/resolve/c10ece1aade47bb51c153c893d14e5bf8e5b7117/ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx' -OutFile "$File.part"
    if ((Get-FileHash "$File.part" -Algorithm SHA256).Hash.ToLowerInvariant() -ne '15fab56e11a097858ee115545d0f697fc2a316c41a291a5362349fb870411b0a') { throw 'SHA-256 не совпал' }
    Move-Item -LiteralPath "$File.part" -Destination $File
} elseif ((Get-FileHash $File -Algorithm SHA256).Hash.ToLowerInvariant() -ne '15fab56e11a097858ee115545d0f697fc2a316c41a291a5362349fb870411b0a') { throw 'SHA-256 не совпал' }
```

```powershell
$File = "$HOME/LocalAISeries/models/ru_RU-denis-medium.onnx.json"
New-Item -ItemType Directory (Split-Path $File -Parent) -Force | Out-Null
if (-not (Test-Path -LiteralPath $File)) {
    Invoke-WebRequest -UseBasicParsing -Uri 'https://huggingface.co/rhasspy/piper-voices/resolve/c10ece1aade47bb51c153c893d14e5bf8e5b7117/ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx.json' -OutFile "$File.part"
    if ((Get-FileHash "$File.part" -Algorithm SHA256).Hash.ToLowerInvariant() -ne '831c860dac0b5073eaa81610a0a638ec23d90a6cf8e5f871b4485c2cec3767c8') { throw 'SHA-256 не совпал' }
    Move-Item -LiteralPath "$File.part" -Destination $File
} elseif ((Get-FileHash $File -Algorithm SHA256).Hash.ToLowerInvariant() -ne '831c860dac0b5073eaa81610a0a638ec23d90a6cf8e5f871b4485c2cec3767c8') { throw 'SHA-256 не совпал' }
```

```powershell
$File = "$HOME/LocalAISeries/models/denis-MODEL_CARD.txt"
New-Item -ItemType Directory (Split-Path $File -Parent) -Force | Out-Null
if (-not (Test-Path -LiteralPath $File)) {
    Invoke-WebRequest -UseBasicParsing -Uri 'https://huggingface.co/rhasspy/piper-voices/resolve/c10ece1aade47bb51c153c893d14e5bf8e5b7117/ru/ru_RU/denis/medium/MODEL_CARD' -OutFile "$File.part"
    if ((Get-FileHash "$File.part" -Algorithm SHA256).Hash.ToLowerInvariant() -ne '8b5d685dd80f8ad3f8dbbe1c56b16bb0809f00c144af3642dbcf3b707eb89c12') { throw 'SHA-256 не совпал' }
    Move-Item -LiteralPath "$File.part" -Destination $File
} elseif ((Get-FileHash $File -Algorithm SHA256).Hash.ToLowerInvariant() -ne '8b5d685dd80f8ad3f8dbbe1c56b16bb0809f00c144af3642dbcf3b707eb89c12') { throw 'SHA-256 не совпал' }
```

Записать сборку, модели и библиотеки в учёт установки.

```powershell
& "$HOME/LocalAISeries/env/Scripts/python.exe" -B -c @'
from pathlib import Path
from lib.common import owned_root
root = owned_root(Path.home() / 'LocalAISeries')
from lib.common import LOCK
from manage import read_state, installed_packages, whisper_binary
assert whisper_binary(root).is_file()
state = read_state(root)
state['artifacts']['whisper-source'] = {**LOCK['artifacts']['whisper-source'], 'status': 'verified', 'path': str(root / 'cache/downloads/whisper-source.download')}
for key, name in [('whisper-model', 'ggml-base.bin'), ('piper-model', 'ru_RU-denis-medium.onnx'), ('piper-config', 'ru_RU-denis-medium.onnx.json'), ('piper-card', 'denis-MODEL_CARD.txt')]:
    state['artifacts'][key] = {**LOCK['artifacts'][key], 'status': 'verified', 'path': str(root / 'models' / name)}
(root / 'build/whisper/.complete').write_text(LOCK['whisper_commit'])
state['programs']['whisper.cpp'] = {'version': LOCK['whisper_version'], 'commit': LOCK['whisper_commit'], 'ownership': 'built from source'}
state['stage'] = max(state['stage'], 4)
installed_packages(root, state)
print('STAGE 4: OK')
'@
if ($LASTEXITCODE) { throw 'Python: ошибка выполнения' }
```

### 6. Запустить помощника на CPU

Команда запуска использует установленные файлы из `LocalAISeries`.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& "$HOME/local-ai-kit/local-ai.ps1" start -Stage 4
```

## Запустить с готовой сборкой Vulkan

После `Ctrl+C` выполните команду своей ОС.

### 1. Ubuntu

```bash
bash "$HOME/local-ai-kit/local-ai.sh" start --stage 4 --backend vulkan
```

### 2. Windows

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& "$HOME/local-ai-kit/local-ai.ps1" start -Stage 4 -Backend vulkan
```

## Голосовой вопрос

1. «Настройки»: лимит генерации `384`, рассуждения выключены → «Применить».
2. Включите «Озвучивать ответ».
3. Нажмите «Записать голос», разрешите микрофон и произнесите: «Какой код проекта Сапфир? Ответь одним коротким предложением».
4. Нажмите «Остановить запись», проверьте текст → «Отправить».

Ожидаемый результат: распознанный вопрос, текстовый ответ с `4182`, затем голосовой ответ. При запросе браузера нажмите ▶.

Одна запись — до 29 секунд; озвучка ответа — до 1600 символов.

## Полное удаление

Остановите проект через `Ctrl+C`. Команда удаления сама покажет список ресурсов и запросит подтверждение:

### 1. Ubuntu

```bash
bash "$HOME/local-ai-kit/local-ai.sh" remove
```

### 2. Windows

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& "$HOME/local-ai-kit/local-ai.ps1" remove
```

Проверьте список ресурсов. Введите `DELETE` для удаления установки вместе с её моделями, данными и кэшами. Распакованную папку `local-ai-kit` и скачанный архив удалите через файловый менеджер. Закройте терминал.

## Автоматическая установка

Распакуйте проект в папку `local-ai-kit` внутри домашней папки. Перед установкой остановите работающий чат через `Ctrl+C`.

### Ubuntu

Установка:

```bash
bash "$HOME/local-ai-kit/local-ai.sh" install --stage 4 --backend cpu
```

Запуск:

```bash
bash "$HOME/local-ai-kit/local-ai.sh" start --stage 4 --backend cpu
```

### Windows

Откройте 64-разрядный PowerShell. При блокировке Smart App Control его необходимо отключить. Microsoft Defender оставьте включённым.

Установка:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& "$HOME\local-ai-kit\local-ai.ps1" install -Stage 4 -Backend cpu
```

Запуск в том же окне:

```powershell
& "$HOME\local-ai-kit\local-ai.ps1" start -Stage 4 -Backend cpu
```

`Stage 4` — четвертый этап; `Backend cpu` — вычисления на процессоре. После запуска откроется чат в браузере. Остановка — `Ctrl+C`.
