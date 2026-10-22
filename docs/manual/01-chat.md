# 1. Локальный чат

Распакуйте архив проекта через файловый менеджер в домашнюю папку и назовите распакованную папку `local-ai-kit`. В ней находится код интерфейса и команды запуска. Модели, сборки и данные устанавливаются отдельно в `LocalAISeries`.

## Ubuntu 24.04/26.04 x86-64

### 1. Подготовить Ubuntu и открыть папку программы

Откройте терминал сочетанием `Ctrl+Alt+T`. Штатный Python Ubuntu запускает подготовительные команды.

```bash
if ! command -v python3 >/dev/null; then
  sudo apt-get update &&
  apt-get -s --no-install-recommends --no-upgrade install python3 > "$HOME/local-ai-kit/python-bootstrap-plan.txt" &&
  sudo apt-get install --no-install-recommends --no-upgrade --no-remove python3
fi
python3 --version
```

Перейти в папку с кодом программы.

```bash
cd "$HOME/local-ai-kit/app"
export PYTHONDONTWRITEBYTECODE=1
```

```bash
bash "$HOME/local-ai-kit/local-ai.sh" hardware
```

### 2. Создать папку установки и установить отдельный Python 3.12.15

Блок создаёт папку установки и метку принадлежности проекту для удаления.

```bash
python3 -B - <<'PY'
from pathlib import Path
from lib.common import owned_root
root = owned_root(Path.home() / 'LocalAISeries', create=True)
for folder in ('state', 'models', 'data/workspace', 'data/documents', 'logs', 'tmp'):
    (root / folder).mkdir(parents=True, exist_ok=True)
plan = Path.home() / 'local-ai-kit/python-bootstrap-plan.txt'
if plan.exists():
    import re
    from lib.common import atomic_json
    from manage import dpkg_packages, read_state, save_state
    state = read_state(root)
    current = dpkg_packages(include_incomplete=True)
    for line in plan.read_text().splitlines():
        match = re.match(r'Inst (\S+) \((\S+)', line)
        if match and current.get(match[1]) == match[2]:
            state['apt_owned'][match[1]] = match[2]
    atomic_json(root / 'state/apt-before.json', {k:v for k,v in current.items() if k not in state['apt_owned']})
    save_state(root, state)
    plan.unlink()
print(root)
PY
```

Скачать отдельный Python 3.12.15, проверить SHA-256 и распаковать в `LocalAISeries/python`.

```bash
mkdir -p "$(dirname "$HOME/LocalAISeries/cache/downloads/python-linux.download")"
if [ ! -f "$HOME/LocalAISeries/cache/downloads/python-linux.download" ]; then
  python3 -B -c 'from pathlib import Path; from urllib.request import urlretrieve; urlretrieve("https://github.com/astral-sh/python-build-standalone/releases/download/20261013/cpython-3.12.15%2B20261013-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz", Path.home() / "LocalAISeries/cache/downloads/python-linux.download.part")'
  printf '%s  %s\n' '178d3d83b6e8e99285a65d3fce9c16b87952cc5efdb4d1a0e3ff3be18ff0fc9c' "$HOME/LocalAISeries/cache/downloads/python-linux.download.part" | sha256sum --check - &&
  mv "$HOME/LocalAISeries/cache/downloads/python-linux.download.part" "$HOME/LocalAISeries/cache/downloads/python-linux.download"
else
  printf '%s  %s\n' '178d3d83b6e8e99285a65d3fce9c16b87952cc5efdb4d1a0e3ff3be18ff0fc9c' "$HOME/LocalAISeries/cache/downloads/python-linux.download" | sha256sum --check -
fi
```

```bash
mkdir -p "$HOME/LocalAISeries/python"
tar -xf "$HOME/LocalAISeries/cache/downloads/python-linux.download" -C "$HOME/LocalAISeries/python" --strip-components=1
```

Создать окружение для библиотек в `LocalAISeries/env`.

```bash
export TMPDIR="$HOME/LocalAISeries/tmp"
export XDG_CACHE_HOME="$HOME/LocalAISeries/cache/xdg"
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME"
"$HOME/LocalAISeries/python/bin/python3" -B -m venv "$HOME/LocalAISeries/env" &&
"$HOME/LocalAISeries/env/bin/python" --version
```

### 3. Установить CMake, psutil и компилятор

CMake 4.1.2 собирает движок, psutil 7.2.2 проверяет память и процессы. Файл `locks/base-linux.txt` входит в архив проекта: в нём записаны точные версии библиотек и SHA-256.

```bash
"$HOME/LocalAISeries/env/bin/python" -m pip --isolated install --require-hashes --only-binary=:all: --no-input --disable-pip-version-check --cache-dir "$HOME/LocalAISeries/cache/pip" -r "$HOME/local-ai-kit/locks/base-linux.txt" &&
"$HOME/LocalAISeries/env/bin/python" -m pip --isolated check
```

`--require-hashes` проверяет хеши пакетов, `--only-binary=:all:` выбирает готовые пакеты Python, `--cache-dir` задаёт кэш проекта.

```bash
mkdir -p "$HOME/LocalAISeries/cache/apt/archives/partial" "$HOME/LocalAISeries/cache/apt/lists/partial"
sudo apt-get -o "Dir::Cache::archives=$HOME/LocalAISeries/cache/apt/archives" -o "Dir::State::lists=$HOME/LocalAISeries/cache/apt/lists" -o APT::Sandbox::User=root update
```

Проверить план APT и записать новые пакеты до установки.

```bash
"$HOME/LocalAISeries/env/bin/python" -B - <<'PY'
from pathlib import Path
from lib.common import owned_root
root = owned_root(Path.home() / 'LocalAISeries')
import json, re, subprocess
from lib.common import atomic_json
from manage import dpkg_packages, read_state, save_state
state = read_state(root)
before = root / 'state/apt-before.json'
if not before.exists():
    atomic_json(before, dpkg_packages(include_incomplete=True))
baseline = json.loads(before.read_text())
current = dpkg_packages(include_incomplete=True)
options = ['-o', f"Dir::Cache::archives={root / 'cache/apt/archives'}", '-o', f"Dir::State::lists={root / 'cache/apt/lists'}", '-o', 'APT::Sandbox::User=root']
plan = subprocess.run(['apt-get', *options, '-s', '--no-install-recommends', 'install', 'build-essential'], check=True, capture_output=True, text=True).stdout
packages = []
for line in plan.splitlines():
    if not line.startswith('Inst '):
        continue
    match = re.match(r'Inst (\S+)(?: \[([^]]+)\])? \((\S+)', line)
    if not match:
        raise RuntimeError(line)
    name, previous, version = match.groups()
    if (previous or name in current) and name not in state['apt_owned']:
        raise RuntimeError('APT хочет обновить общую программу: ' + name)
    if name in state['apt_owned'] and state['apt_owned'][name] != version:
        raise RuntimeError('Версия пакета изменилась: ' + name)
    packages.append(name + '=' + version)
    if name not in baseline:
        state['apt_owned'][name] = version
if 'build-essential' in baseline and 'build-essential' in current:
    state['apt_borrowed']['build-essential'] = current['build-essential']
save_state(root, state)
(root / 'state/apt-install.txt').write_text('\n'.join(packages))
atomic_json(root / 'state/apt-lock.json', state['apt_owned'])
print(plan)
PY
```

Установить запланированные версии GCC, G++ и Make.

```bash
if [ -s "$HOME/LocalAISeries/state/apt-install.txt" ]; then
  xargs -r sudo apt-get -o "Dir::Cache::archives=$HOME/LocalAISeries/cache/apt/archives" -o "Dir::State::lists=$HOME/LocalAISeries/cache/apt/lists" -o APT::Sandbox::User=root install -y --no-install-recommends --no-upgrade --no-remove < "$HOME/LocalAISeries/state/apt-install.txt"
fi
gcc --version
g++ --version
make --version
```

Версии компилятора сохраняются в учёт установки после успешной сборки сервера.

### 4. Скачать исходники llama.cpp и файлы интерфейса

Архивы проверяются по SHA-256. `llama-source` содержит исходный код движка; `ui` — страницы интерфейса для сборки сервера.

```bash
mkdir -p "$(dirname "$HOME/LocalAISeries/cache/downloads/llama-source.download")"
if [ ! -f "$HOME/LocalAISeries/cache/downloads/llama-source.download" ]; then
  "$HOME/LocalAISeries/env/bin/python" -B -c 'from pathlib import Path; from urllib.request import urlretrieve; urlretrieve("https://codeload.github.com/ggml-org/llama.cpp/tar.gz/620d2225cc436ab0b001e3200e590e3b286ef9ab", Path.home() / "LocalAISeries/cache/downloads/llama-source.download.part")'
  printf '%s  %s\n' '1d4a987d9bd048f6e93107e838026438df70fbde237fc0c69c63d600512b4bd9' "$HOME/LocalAISeries/cache/downloads/llama-source.download.part" | sha256sum --check - &&
  mv "$HOME/LocalAISeries/cache/downloads/llama-source.download.part" "$HOME/LocalAISeries/cache/downloads/llama-source.download"
else
  printf '%s  %s\n' '1d4a987d9bd048f6e93107e838026438df70fbde237fc0c69c63d600512b4bd9' "$HOME/LocalAISeries/cache/downloads/llama-source.download" | sha256sum --check -
fi
```

```bash
mkdir -p "$HOME/LocalAISeries/src/llama.cpp"
tar -xf "$HOME/LocalAISeries/cache/downloads/llama-source.download" -C "$HOME/LocalAISeries/src/llama.cpp" --strip-components=1 &&
printf '%s' '1d4a987d9bd048f6e93107e838026438df70fbde237fc0c69c63d600512b4bd9' > "$HOME/LocalAISeries/src/llama.cpp/.local-ai-source-sha256"
```

```bash
mkdir -p "$(dirname "$HOME/LocalAISeries/cache/downloads/ui.download")"
if [ ! -f "$HOME/LocalAISeries/cache/downloads/ui.download" ]; then
  "$HOME/LocalAISeries/env/bin/python" -B -c 'from pathlib import Path; from urllib.request import urlretrieve; urlretrieve("https://huggingface.co/buckets/ggml-org/llama-ui/resolve/b11669/dist.tar.gz?download=true", Path.home() / "LocalAISeries/cache/downloads/ui.download.part")'
  printf '%s  %s\n' '81d35456d45e17b5650fd8cc64d10f920e033e31cbbbc959eceeb0e47b6a3d4b' "$HOME/LocalAISeries/cache/downloads/ui.download.part" | sha256sum --check - &&
  mv "$HOME/LocalAISeries/cache/downloads/ui.download.part" "$HOME/LocalAISeries/cache/downloads/ui.download"
else
  printf '%s  %s\n' '81d35456d45e17b5650fd8cc64d10f920e033e31cbbbc959eceeb0e47b6a3d4b' "$HOME/LocalAISeries/cache/downloads/ui.download" | sha256sum --check -
fi
```

```bash
mkdir -p "$HOME/LocalAISeries/src/llama.cpp/tools/ui/dist"
tar -xf "$HOME/LocalAISeries/cache/downloads/ui.download" -C "$HOME/LocalAISeries/src/llama.cpp/tools/ui/dist"
```

Архивы скачиваются по указанным адресам и проверяются по SHA-256. Исходники распаковываются в `LocalAISeries/src/llama.cpp`.

### 5. Собрать llama-server для CPU

Результат сборки: `LocalAISeries/build/llama-cpu/bin/llama-server` на Ubuntu и `llama-server.exe` на Windows.

```bash
AiCmake="$HOME/LocalAISeries/env/bin/cmake"
AiLlamaFlags=(
  -DCMAKE_BUILD_TYPE=Release
  -DBUILD_SHARED_LIBS=OFF
  -DLLAMA_BUILD_TESTS=OFF
  -DLLAMA_BUILD_EXAMPLES=OFF
  -DLLAMA_BUILD_APP=OFF
  -DLLAMA_OPENSSL=OFF
  -DLLAMA_SUBPROCESS=OFF
  -DLLAMA_BUILD_UI=OFF
  -DLLAMA_USE_PREBUILT_UI=OFF
  -DGGML_CUDA=OFF
  -DLLAMA_BUILD_NUMBER=11669
  -DLLAMA_BUILD_COMMIT=620d222
)
"$AiCmake" -S "$HOME/LocalAISeries/src/llama.cpp" -B "$HOME/LocalAISeries/build/llama-cpu" "${AiLlamaFlags[@]}" -DGGML_VULKAN=OFF &&
"$AiCmake" --build "$HOME/LocalAISeries/build/llama-cpu" --config Release --parallel 1 --target llama-server
```

`-S` — исходники; `-B` — папка сборки; `Release` — оптимизация; `--parallel 1` — одна задача сборки; `--target llama-server` — сервер модели.

```bash
"$HOME/LocalAISeries/env/bin/python" -B - <<'PY'
from pathlib import Path
from lib.common import owned_root
root = owned_root(Path.home() / 'LocalAISeries')
from lib.common import LOCK, execute
from manage import read_state, save_state, server_binary
state = read_state(root)
binary = server_binary(root, 'cpu')
info = execute([binary, '--version'], root, capture=True)
assert LOCK['llama_commit'][:7] in info.stdout + info.stderr
(root / 'build/llama-cpu/.complete').write_text(LOCK['llama_commit'])
for key in ('llama-source', 'ui'):
    state['artifacts'][key] = {**LOCK['artifacts'][key], 'status': 'verified', 'path': str(root / 'cache/downloads' / (key + '.download'))}
import shutil, subprocess
for name in ('gcc', 'g++', 'make'):
    info = subprocess.run([name, '--version'], check=True, capture_output=True, text=True).stdout.splitlines()[0]
    state['programs'][name] = {'version': info, 'ownership': 'apt recorded / existing', 'path': shutil.which(name)}
state['programs']['llama-cpu'] = {'version': LOCK['llama_version'], 'commit': LOCK['llama_commit'], 'ownership': 'built from source'}
save_state(root, state)
print('LLAMA CPU: OK')
PY
```

### 6. Скачать модель Qwen3.5-9B Q4_K_M

```bash
mkdir -p "$(dirname "$HOME/LocalAISeries/models/Qwen3.5-9B-Q4_K_M.gguf")"
if [ ! -f "$HOME/LocalAISeries/models/Qwen3.5-9B-Q4_K_M.gguf" ]; then
  "$HOME/LocalAISeries/env/bin/python" -B -c 'from pathlib import Path; from urllib.request import urlretrieve; urlretrieve("https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/3885219b6810b007914f3a7950a8d1b469d598a5/Qwen3.5-9B-Q4_K_M.gguf", Path.home() / "LocalAISeries/models/Qwen3.5-9B-Q4_K_M.gguf.part")'
  printf '%s  %s\n' '03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8' "$HOME/LocalAISeries/models/Qwen3.5-9B-Q4_K_M.gguf.part" | sha256sum --check - &&
  mv "$HOME/LocalAISeries/models/Qwen3.5-9B-Q4_K_M.gguf.part" "$HOME/LocalAISeries/models/Qwen3.5-9B-Q4_K_M.gguf"
else
  printf '%s  %s\n' '03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8' "$HOME/LocalAISeries/models/Qwen3.5-9B-Q4_K_M.gguf" | sha256sum --check -
fi
```

Записать модель, библиотеки и готовность первого этапа в учёт установки.

```bash
"$HOME/LocalAISeries/env/bin/python" -B - <<'PY'
from pathlib import Path
from lib.common import owned_root
root = owned_root(Path.home() / 'LocalAISeries')
from lib.models import catalog, selected_settings, save_settings
from manage import read_state, installed_packages
settings = selected_settings(root)
module = catalog(root)[settings['model']]
path = root / 'models' / module['file']
assert path.stat().st_size == module['size']
state = read_state(root)
state['artifacts']['model/' + module['id']] = {**module, 'status': 'verified', 'path': str(path)}
state['stage'] = max(state['stage'], 1)
installed_packages(root, state)
save_settings(root, settings)
print('Этап 1: готово')
PY
```

Файл модели сохраняется в `LocalAISeries/models`. Занимает примерно 5,7 ГБ; проверка SHA-256 должна завершиться успешно.

### 7. Запустить чат на CPU

Команду запуска можно выполнять из любого нового терминала.

```bash
bash "$HOME/local-ai-kit/local-ai.sh" start --stage 1
```

`--stage 1` / `-Stage 1` включает чат и настройки. Откроется `http://127.0.0.1:8080`.

Остановка — `Ctrl+C`.

### 8. Собрать дополнительный вариант Vulkan для GPU

Для NVIDIA, AMD или Intel с установленным драйвером Vulkan. Остановите чат через `Ctrl+C`. Выполните следующие команды в том же терминале: они скачивают Vulkan SDK 1.4.363.0 в папку проекта и собирают сервер с поддержкой GPU.

```bash
mkdir -p "$(dirname "$HOME/LocalAISeries/cache/downloads/vulkan-linux.download")"
if [ ! -f "$HOME/LocalAISeries/cache/downloads/vulkan-linux.download" ]; then
  "$HOME/LocalAISeries/env/bin/python" -B -c 'from pathlib import Path; from urllib.request import urlretrieve; urlretrieve("https://sdk.lunarg.com/sdk/download/1.4.363.0/linux/vulkansdk-linux-x86_64-1.4.363.0.tar.xz", Path.home() / "LocalAISeries/cache/downloads/vulkan-linux.download.part")'
  printf '%s  %s\n' '197962f5cbf80baf2775a03336a01cee7c8745686c65aaa70d3f751ade4d7e43' "$HOME/LocalAISeries/cache/downloads/vulkan-linux.download.part" | sha256sum --check - &&
  mv "$HOME/LocalAISeries/cache/downloads/vulkan-linux.download.part" "$HOME/LocalAISeries/cache/downloads/vulkan-linux.download"
else
  printf '%s  %s\n' '197962f5cbf80baf2775a03336a01cee7c8745686c65aaa70d3f751ade4d7e43' "$HOME/LocalAISeries/cache/downloads/vulkan-linux.download" | sha256sum --check -
fi
```

```bash
mkdir -p "$HOME/LocalAISeries/tools/vulkan"
tar -xf "$HOME/LocalAISeries/cache/downloads/vulkan-linux.download" -C "$HOME/LocalAISeries/tools/vulkan" --strip-components=1
```

Записать версию SDK в учёт установки.

```bash
"$HOME/LocalAISeries/env/bin/python" -B - <<'PY'
from pathlib import Path
from lib.common import owned_root
root = owned_root(Path.home() / 'LocalAISeries')
from manage import read_state, save_state
(root / 'tools/vulkan/.local-ai-sdk-complete').write_text('1.4.363.0\n')
state = read_state(root)
from lib.common import LOCK
key = 'vulkan-windows' if __import__('os').name == 'nt' else 'vulkan-linux'
filename = 'vulkan-sdk.exe' if key.endswith('windows') else 'vulkan-linux.download'
state['artifacts'][key] = {**LOCK['artifacts'][key], 'status': 'verified', 'path': str(root / 'cache/downloads' / filename)}
state['programs']['Vulkan SDK'] = {'version': '1.4.363.0', 'ownership': 'private copy only', 'path': str(root / 'tools/vulkan')}
save_state(root, state)
PY
```

```bash
export VULKAN_SDK="$HOME/LocalAISeries/tools/vulkan/x86_64"
export PATH="$VULKAN_SDK/bin:$PATH"
export LD_LIBRARY_PATH="$VULKAN_SDK/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
```

```bash
"$AiCmake" -S "$HOME/LocalAISeries/src/llama.cpp" -B "$HOME/LocalAISeries/build/llama-vulkan" "${AiLlamaFlags[@]}" -DGGML_VULKAN=ON &&
"$AiCmake" --build "$HOME/LocalAISeries/build/llama-vulkan" --config Release --parallel 1 --target llama-server
```

```bash
"$HOME/LocalAISeries/env/bin/python" -B - <<'PY'
from pathlib import Path
from lib.common import owned_root
root = owned_root(Path.home() / 'LocalAISeries')
from lib.common import LOCK, execute
from manage import read_state, save_state, server_binary
state = read_state(root)
binary = server_binary(root, 'vulkan')
info = execute([binary, '--version'], root, capture=True)
assert LOCK['llama_commit'][:7] in info.stdout + info.stderr
(root / 'build/llama-vulkan/.complete').write_text(LOCK['llama_commit'])
state['programs']['llama-vulkan'] = {'version': LOCK['llama_version'], 'commit': LOCK['llama_commit'], 'ownership': 'built from source'}
save_state(root, state)
print('LLAMA VULKAN: OK')
PY
```

```bash
bash "$HOME/local-ai-kit/local-ai.sh" hardware
```

`Vulkan0` — идентификатор GPU из вывода `hardware`.

```bash
bash "$HOME/local-ai-kit/local-ai.sh" start --stage 1 --backend vulkan
```

Во втором терминале проверить использование GPU:

```bash
bash "$HOME/local-ai-kit/local-ai.sh" check --stage 1 --backend vulkan
```

Для подтверждения вычислений: `GPU_LAYERS_OFFLOADED`, `GPU_BUFFERS`, `GPU_EXECUTION_COUNTER` — `PASS`.

Запуск на CPU после `Ctrl+C`:

```bash
bash "$HOME/local-ai-kit/local-ai.sh" start --stage 1
```

## Windows 10/11 x64

### Перед установкой на Windows 11
Smart App Control появился в Windows 11. Он проверяет подписи и репутацию программ и может блокировать компоненты проекта.
При блокировке: Безопасность Windows → Управление приложениями и браузером → Параметры интеллектуального управления приложениями → Выкл.
Другие компоненты безопасности не меняются.

### 1. Открыть 64-разрядный PowerShell и папку программы

```powershell
Set-Location "$HOME/local-ai-kit/app"
$ErrorActionPreference = 'Stop'
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
$env:PYTHONDONTWRITEBYTECODE = '1'
```

```powershell
& "$HOME/local-ai-kit/local-ai.ps1" hardware
```

### 2. Скачать отдельный Python 3.12.15 и создать окружение

Блок создаёт папку установки, скачивает Python, проверяет SHA-256 и распаковывает его в `LocalAISeries/python`. Файл `locks/versions.json` входит в комплект и содержит закреплённый адрес и SHA-256 Python 3.12.15. Системный Python для Windows-команд не требуется.

```powershell
$AiRoot = [IO.Path]::GetFullPath("$HOME/LocalAISeries")
$AiMarker = Join-Path $AiRoot 'project.json'
if (Test-Path $AiMarker) {
    $AiProject = Get-Content $AiMarker -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($AiProject.project -ne 'local-ai-youtube-2026-v1' -or $AiProject.root -ne $AiRoot) { throw 'Папка принадлежит другому проекту' }
} else {
    if ((Test-Path $AiRoot) -and @(Get-ChildItem $AiRoot -Force).Count) { throw 'Папка установки содержит посторонние файлы' }
    New-Item -ItemType Directory $AiRoot -Force | Out-Null
    @{project='local-ai-youtube-2026-v1';root=$AiRoot;id=[guid]::NewGuid().ToString('N')} | ConvertTo-Json | Set-Content $AiMarker -Encoding UTF8
}
$AiDownloads = Join-Path $AiRoot 'cache/downloads'
New-Item -ItemType Directory $AiDownloads -Force | Out-Null
$env:TEMP = Join-Path $AiRoot 'tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory $env:TEMP -Force | Out-Null
$AiLock = Get-Content "$HOME/local-ai-kit/locks/versions.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$AiRuntime = $AiLock.artifacts.'python-windows'
$AiArchive = Join-Path $AiDownloads 'python-windows.download'
if (-not (Test-Path $AiArchive)) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $AiRuntime.url -OutFile ($AiArchive+'.part')
    if ((Get-FileHash ($AiArchive+'.part') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $AiRuntime.sha256) { throw 'SHA-256 Python не совпал' }
    Move-Item ($AiArchive+'.part') $AiArchive
}
if ((Get-FileHash $AiArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $AiRuntime.sha256) { throw 'SHA-256 Python не совпал' }
$AiRuntimePython = Join-Path $AiRoot 'python/python.exe'
if (-not (Test-Path $AiRuntimePython)) {
    tar.exe -xf $AiArchive -C $AiRoot
    if ($LASTEXITCODE) { throw 'Python: распаковка не завершена' }
}
```

```powershell
& "$HOME/LocalAISeries/python/python.exe" -B -m venv "$HOME/LocalAISeries/env"
if ($LASTEXITCODE) { throw 'Окружение Python не создано' }
& "$HOME/LocalAISeries/env/Scripts/python.exe" --version
if ($LASTEXITCODE) { throw 'Python не запускается' }
New-Item -ItemType Directory "$HOME/LocalAISeries/state", "$HOME/LocalAISeries/models", "$HOME/LocalAISeries/data/workspace", "$HOME/LocalAISeries/data/documents", "$HOME/LocalAISeries/logs" -Force | Out-Null
```

### 3. Установить библиотеки Python и компилятор w64devkit

Файл `locks/base-windows.txt` из архива закрепляет версии psutil и библиотек выполнения Windows. w64devkit 2.10.1 содержит GCC, G++, CMake и Ninja и устанавливается в `LocalAISeries/tools/w64devkit`.

```powershell
& "$HOME/LocalAISeries/env/Scripts/python.exe" -m pip --isolated install --require-hashes '--only-binary=:all:' --no-input --disable-pip-version-check --cache-dir "$HOME/LocalAISeries/cache/pip" -r "$HOME/local-ai-kit/locks/base-windows.txt"
if ($LASTEXITCODE) { throw 'pip: установка не завершена' }
& "$HOME/LocalAISeries/env/Scripts/python.exe" -m pip --isolated check
if ($LASTEXITCODE) { throw 'pip: зависимости несовместимы' }
```

`--require-hashes` проверяет хеши пакетов, `--only-binary=:all:` выбирает готовые пакеты Python, `--cache-dir` задаёт кэш проекта.

```powershell
$File = "$HOME/LocalAISeries/cache/downloads/w64devkit.exe"
New-Item -ItemType Directory (Split-Path $File -Parent) -Force | Out-Null
if (-not (Test-Path -LiteralPath $File)) {
    Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/skeeto/w64devkit/releases/download/v2.10.1/w64devkit-x64-2.10.1.7z.exe' -OutFile "$File.part"
    if ((Get-FileHash "$File.part" -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'add1edf984ce4d473cfeb7c52e0ab38db73a855bba6c7f564d5e16648eb2896a') { throw 'SHA-256 не совпал' }
    Move-Item -LiteralPath "$File.part" -Destination $File
} elseif ((Get-FileHash $File -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'add1edf984ce4d473cfeb7c52e0ab38db73a855bba6c7f564d5e16648eb2896a') { throw 'SHA-256 не совпал' }
```

```powershell
New-Item -ItemType Directory "$HOME/LocalAISeries/tools" -Force | Out-Null
& "$HOME/LocalAISeries/cache/downloads/w64devkit.exe" -y "-o$HOME/LocalAISeries/tools"
if ($LASTEXITCODE) { throw 'Компилятор не распакован' }
& "$HOME/LocalAISeries/tools/w64devkit/bin/gcc.exe" --version
if ($LASTEXITCODE) { throw 'Компилятор не запускается' }
```

Версии компилятора сохраняются в учёт установки после успешной сборки сервера.

### 4. Скачать исходники llama.cpp и файлы интерфейса

Архивы проверяются по SHA-256. `llama-source` содержит исходный код движка; `ui` — страницы интерфейса для сборки сервера.

```powershell
$File = "$HOME/LocalAISeries/cache/downloads/llama-source.download"
New-Item -ItemType Directory (Split-Path $File -Parent) -Force | Out-Null
if (-not (Test-Path -LiteralPath $File)) {
    Invoke-WebRequest -UseBasicParsing -Uri 'https://codeload.github.com/ggml-org/llama.cpp/tar.gz/620d2225cc436ab0b001e3200e590e3b286ef9ab' -OutFile "$File.part"
    if ((Get-FileHash "$File.part" -Algorithm SHA256).Hash.ToLowerInvariant() -ne '1d4a987d9bd048f6e93107e838026438df70fbde237fc0c69c63d600512b4bd9') { throw 'SHA-256 не совпал' }
    Move-Item -LiteralPath "$File.part" -Destination $File
} elseif ((Get-FileHash $File -Algorithm SHA256).Hash.ToLowerInvariant() -ne '1d4a987d9bd048f6e93107e838026438df70fbde237fc0c69c63d600512b4bd9') { throw 'SHA-256 не совпал' }
```

```powershell
New-Item -ItemType Directory "$HOME/LocalAISeries/src/llama.cpp" -Force | Out-Null
tar.exe -xf "$HOME/LocalAISeries/cache/downloads/llama-source.download" -C "$HOME/LocalAISeries/src/llama.cpp" '--strip-components=1'
if ($LASTEXITCODE) { throw 'Ошибка распаковки' }
[IO.File]::WriteAllText("$HOME/LocalAISeries/src/llama.cpp/.local-ai-source-sha256", '1d4a987d9bd048f6e93107e838026438df70fbde237fc0c69c63d600512b4bd9')
```

```powershell
$File = "$HOME/LocalAISeries/cache/downloads/ui.download"
New-Item -ItemType Directory (Split-Path $File -Parent) -Force | Out-Null
if (-not (Test-Path -LiteralPath $File)) {
    Invoke-WebRequest -UseBasicParsing -Uri 'https://huggingface.co/buckets/ggml-org/llama-ui/resolve/b11669/dist.tar.gz?download=true' -OutFile "$File.part"
    if ((Get-FileHash "$File.part" -Algorithm SHA256).Hash.ToLowerInvariant() -ne '81d35456d45e17b5650fd8cc64d10f920e033e31cbbbc959eceeb0e47b6a3d4b') { throw 'SHA-256 не совпал' }
    Move-Item -LiteralPath "$File.part" -Destination $File
} elseif ((Get-FileHash $File -Algorithm SHA256).Hash.ToLowerInvariant() -ne '81d35456d45e17b5650fd8cc64d10f920e033e31cbbbc959eceeb0e47b6a3d4b') { throw 'SHA-256 не совпал' }
```

```powershell
New-Item -ItemType Directory "$HOME/LocalAISeries/src/llama.cpp/tools/ui/dist" -Force | Out-Null
tar.exe -xf "$HOME/LocalAISeries/cache/downloads/ui.download" -C "$HOME/LocalAISeries/src/llama.cpp/tools/ui/dist"
if ($LASTEXITCODE) { throw 'Ошибка распаковки' }
```

Архивы скачиваются по указанным адресам и проверяются по SHA-256. Исходники распаковываются в `LocalAISeries/src/llama.cpp`.

### 5. Собрать llama-server для CPU

Результат сборки: `LocalAISeries/build/llama-cpu/bin/llama-server` на Ubuntu и `llama-server.exe` на Windows.

```powershell
$AiTools = Join-Path "$HOME/LocalAISeries" 'tools/w64devkit/bin'
$AiCmake = Join-Path $AiTools 'cmake.exe'
$env:PATH = "$AiTools;$(Join-Path "$HOME/LocalAISeries" 'python');$env:PATH"
$AiLlamaFlags = @(
  '-DCMAKE_BUILD_TYPE=Release'
  '-DBUILD_SHARED_LIBS=OFF'
  '-DLLAMA_BUILD_TESTS=OFF'
  '-DLLAMA_BUILD_EXAMPLES=OFF'
  '-DLLAMA_BUILD_APP=OFF'
  '-DLLAMA_OPENSSL=OFF'
  '-DLLAMA_SUBPROCESS=OFF'
  '-DLLAMA_BUILD_UI=OFF'
  '-DLLAMA_USE_PREBUILT_UI=OFF'
  '-DGGML_CUDA=OFF'
  '-DLLAMA_BUILD_NUMBER=11669'
  '-DLLAMA_BUILD_COMMIT=620d222'
)
& $AiCmake -S "$HOME/LocalAISeries/src/llama.cpp" -B "$HOME/LocalAISeries/build/llama-cpu" @AiLlamaFlags '-DGGML_VULKAN=OFF' `
  -G Ninja "-DCMAKE_C_COMPILER=$AiTools/gcc.exe" "-DCMAKE_CXX_COMPILER=$AiTools/g++.exe" "-DCMAKE_MAKE_PROGRAM=$AiTools/ninja.exe"
if ($LASTEXITCODE) { throw 'CMake: настройка не завершена' }
& $AiCmake --build "$HOME/LocalAISeries/build/llama-cpu" --config Release --parallel 1 --target llama-server
if ($LASTEXITCODE) { throw 'CMake: сборка не завершена' }
```

`-S` — исходники; `-B` — папка сборки; `Release` — оптимизация; `--parallel 1` — одна задача сборки; `--target llama-server` — сервер модели.

```powershell
& "$HOME/LocalAISeries/env/Scripts/python.exe" -B -c @'
from pathlib import Path
from lib.common import owned_root
root = owned_root(Path.home() / 'LocalAISeries')
from lib.common import LOCK, execute
from manage import read_state, save_state, server_binary
state = read_state(root)
binary = server_binary(root, 'cpu')
info = execute([binary, '--version'], root, capture=True)
assert LOCK['llama_commit'][:7] in info.stdout + info.stderr
(root / 'build/llama-cpu/.complete').write_text(LOCK['llama_commit'])
for key in ('llama-source', 'ui'):
    state['artifacts'][key] = {**LOCK['artifacts'][key], 'status': 'verified', 'path': str(root / 'cache/downloads' / (key + '.download'))}
state['programs']['w64devkit'] = {'version': '2.10.1', 'ownership': 'private', 'path': str(root / 'tools/w64devkit')}
state['artifacts']['w64devkit'] = {**LOCK['artifacts']['w64devkit'], 'status': 'verified', 'path': str(root / 'cache/downloads/w64devkit.exe')}
state['programs']['llama-cpu'] = {'version': LOCK['llama_version'], 'commit': LOCK['llama_commit'], 'ownership': 'built from source'}
save_state(root, state)
print('LLAMA CPU: OK')
'@
if ($LASTEXITCODE) { throw 'Python: ошибка выполнения' }
```

### 6. Скачать модель Qwen3.5-9B Q4_K_M

```powershell
$File = "$HOME/LocalAISeries/models/Qwen3.5-9B-Q4_K_M.gguf"
New-Item -ItemType Directory (Split-Path $File -Parent) -Force | Out-Null
if (-not (Test-Path -LiteralPath $File)) {
    Invoke-WebRequest -UseBasicParsing -Uri 'https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/3885219b6810b007914f3a7950a8d1b469d598a5/Qwen3.5-9B-Q4_K_M.gguf' -OutFile "$File.part"
    if ((Get-FileHash "$File.part" -Algorithm SHA256).Hash.ToLowerInvariant() -ne '03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8') { throw 'SHA-256 не совпал' }
    Move-Item -LiteralPath "$File.part" -Destination $File
} elseif ((Get-FileHash $File -Algorithm SHA256).Hash.ToLowerInvariant() -ne '03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8') { throw 'SHA-256 не совпал' }
```

Записать модель, библиотеки и готовность первого этапа в учёт установки.

```powershell
& "$HOME/LocalAISeries/env/Scripts/python.exe" -B -c @'
from pathlib import Path
from lib.common import owned_root
root = owned_root(Path.home() / 'LocalAISeries')
from lib.models import catalog, selected_settings, save_settings
from manage import read_state, installed_packages
settings = selected_settings(root)
module = catalog(root)[settings['model']]
path = root / 'models' / module['file']
assert path.stat().st_size == module['size']
state = read_state(root)
state['artifacts']['model/' + module['id']] = {**module, 'status': 'verified', 'path': str(path)}
state['stage'] = max(state['stage'], 1)
installed_packages(root, state)
save_settings(root, settings)
print('Этап 1: готово')
'@
if ($LASTEXITCODE) { throw 'Команда Python завершилась с ошибкой' }
```

Файл модели сохраняется в `LocalAISeries/models`. Занимает примерно 5,7 ГБ; проверка SHA-256 должна завершиться успешно.

### 7. Запустить чат на CPU

Команду запуска можно выполнять из любого нового терминала.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& "$HOME/local-ai-kit/local-ai.ps1" start -Stage 1
```

`--stage 1` / `-Stage 1` включает чат и настройки. Откроется `http://127.0.0.1:8080`.

Остановка — `Ctrl+C`.

### 8. Собрать дополнительный вариант Vulkan для GPU

Для NVIDIA, AMD или Intel с установленным драйвером Vulkan. Остановите чат через `Ctrl+C`. Выполните следующие команды в том же терминале: они скачивают Vulkan SDK 1.4.363.0 в папку проекта и собирают сервер с поддержкой GPU.

```powershell
$File = "$HOME/LocalAISeries/cache/downloads/vulkan-sdk.exe"
New-Item -ItemType Directory (Split-Path $File -Parent) -Force | Out-Null
if (-not (Test-Path -LiteralPath $File)) {
    Invoke-WebRequest -UseBasicParsing -Uri 'https://sdk.lunarg.com/sdk/download/1.4.363.0/windows/vulkansdk-windows-X64-1.4.363.0.exe' -OutFile "$File.part"
    if ((Get-FileHash "$File.part" -Algorithm SHA256).Hash.ToLowerInvariant() -ne '94a82d378f7a5e3e54c9db7d2fb7016af136e14ac0a18dbf0f2f67a36352d141') { throw 'SHA-256 не совпал' }
    Move-Item -LiteralPath "$File.part" -Destination $File
} elseif ((Get-FileHash $File -Algorithm SHA256).Hash.ToLowerInvariant() -ne '94a82d378f7a5e3e54c9db7d2fb7016af136e14ac0a18dbf0f2f67a36352d141') { throw 'SHA-256 не совпал' }
```

```powershell
& "$HOME/LocalAISeries/cache/downloads/vulkan-sdk.exe" --root "$HOME/LocalAISeries/tools/vulkan" --accept-licenses --default-answer --confirm-command install copy_only=1
if ($LASTEXITCODE) { throw 'Vulkan SDK не скопирован' }
```

Записать версию SDK в учёт установки.

```powershell
& "$HOME/LocalAISeries/env/Scripts/python.exe" -B -c @'
from pathlib import Path
from lib.common import owned_root
root = owned_root(Path.home() / 'LocalAISeries')
from manage import read_state, save_state
(root / 'tools/vulkan/.local-ai-sdk-complete').write_text('1.4.363.0\n')
state = read_state(root)
from lib.common import LOCK
key = 'vulkan-windows' if __import__('os').name == 'nt' else 'vulkan-linux'
filename = 'vulkan-sdk.exe' if key.endswith('windows') else 'vulkan-linux.download'
state['artifacts'][key] = {**LOCK['artifacts'][key], 'status': 'verified', 'path': str(root / 'cache/downloads' / filename)}
state['programs']['Vulkan SDK'] = {'version': '1.4.363.0', 'ownership': 'private copy only', 'path': str(root / 'tools/vulkan')}
save_state(root, state)
'@
if ($LASTEXITCODE) { throw 'Команда Python завершилась с ошибкой' }
```

```powershell
$env:VULKAN_SDK = Join-Path "$HOME/LocalAISeries" 'tools/vulkan'
$env:PATH = "$env:VULKAN_SDK/Bin;$env:PATH"
```

```powershell
& $AiCmake -S "$HOME/LocalAISeries/src/llama.cpp" -B "$HOME/LocalAISeries/build/llama-vulkan" @AiLlamaFlags '-DGGML_VULKAN=ON' `
  -G Ninja "-DCMAKE_C_COMPILER=$AiTools/gcc.exe" "-DCMAKE_CXX_COMPILER=$AiTools/g++.exe" "-DCMAKE_MAKE_PROGRAM=$AiTools/ninja.exe" `
  "-DVulkan_INCLUDE_DIR=$env:VULKAN_SDK/Include" `
  "-DVulkan_LIBRARY=$env:VULKAN_SDK/Lib/vulkan-1.lib" `
  "-DVulkan_GLSLC_EXECUTABLE=$env:VULKAN_SDK/Bin/glslc.exe"
if ($LASTEXITCODE) { throw 'CMake: настройка не завершена' }
& $AiCmake --build "$HOME/LocalAISeries/build/llama-vulkan" --config Release --parallel 1 --target llama-server
if ($LASTEXITCODE) { throw 'CMake: сборка не завершена' }
```

```powershell
& "$HOME/LocalAISeries/env/Scripts/python.exe" -B -c @'
from pathlib import Path
from lib.common import owned_root
root = owned_root(Path.home() / 'LocalAISeries')
from lib.common import LOCK, execute
from manage import read_state, save_state, server_binary
state = read_state(root)
binary = server_binary(root, 'vulkan')
info = execute([binary, '--version'], root, capture=True)
assert LOCK['llama_commit'][:7] in info.stdout + info.stderr
(root / 'build/llama-vulkan/.complete').write_text(LOCK['llama_commit'])
state['programs']['llama-vulkan'] = {'version': LOCK['llama_version'], 'commit': LOCK['llama_commit'], 'ownership': 'built from source'}
save_state(root, state)
print('LLAMA VULKAN: OK')
'@
if ($LASTEXITCODE) { throw 'Python: ошибка выполнения' }
```

```powershell
& "$HOME/local-ai-kit/local-ai.ps1" hardware
```

`Vulkan0` — идентификатор GPU из вывода `hardware`.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& "$HOME/local-ai-kit/local-ai.ps1" start -Stage 1 -Backend vulkan
```

Во втором терминале проверить использование GPU:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& "$HOME/local-ai-kit/local-ai.ps1" check -Stage 1 -Backend vulkan
```

Для подтверждения вычислений: `GPU_LAYERS_OFFLOADED`, `GPU_BUFFERS`, `GPU_EXECUTION_COUNTER` — `PASS`.

Запуск на CPU после `Ctrl+C`:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& "$HOME/local-ai-kit/local-ai.ps1" start -Stage 1
```

## Настройки и диалог

В браузере откройте «Настройки»: контекст `4096`, температура `0.2`, лимит генерации `384`, рассуждения выключены. Нажмите «Применить».

Контекст — общий объём запроса и ответа в токенах. Лимит генерации ограничивает ответ вместе с рассуждениями. Температура управляет вариативностью ответа.

В новом диалоге отправьте: «Запомни число 37». Затем: «Какое число я назвал?».

Ожидаемый ответ содержит `37`.

## Калькулятор

В новом диалоге отправьте:

> Создай один HTML-файл калькулятора стоимости работы: часы × ставка. Два числовых поля, кнопка «Рассчитать», результат в рублях. Подписи на русском, кодировка UTF-8. Встроенный JavaScript, без внешних библиотек. Не больше 25 строк. Выведи только код.

Сохраните код без обрамляющих строк в файл `calculator.html` в UTF-8. Откройте его в браузере. Значения `3` и `600` должны дать `1800`.

## Рассуждения

«Настройки» → включите «Рассуждения»; «Дополнительно» → бюджет рассуждений `128` → «Применить».

Отправьте: «Три часа работы по 600 рублей. Скидка 10 процентов. Сколько заплатить? Объясни кратко».

Ожидаемый результат: `1620`. После проверки выключите «Рассуждения» → «Применить».

## Автоматическая установка

Распакуйте проект в папку `local-ai-kit` внутри домашней папки. Перед установкой остановите работающий чат через `Ctrl+C`.

### Ubuntu

Установка:

```bash
bash "$HOME/local-ai-kit/local-ai.sh" install --stage 1 --backend cpu
```

Запуск:

```bash
bash "$HOME/local-ai-kit/local-ai.sh" start --stage 1 --backend cpu
```

### Windows

Откройте 64-разрядный PowerShell. При блокировке Smart App Control его необходимо отключить. Microsoft Defender оставьте включённым.

Установка:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& "$HOME\local-ai-kit\local-ai.ps1" install -Stage 1 -Backend cpu
```

Запуск в том же окне:

```powershell
& "$HOME\local-ai-kit\local-ai.ps1" start -Stage 1 -Backend cpu
```

`Stage 1` — первый этап; `Backend cpu` — вычисления на процессоре. После запуска откроется чат в браузере. Остановка — `Ctrl+C`.
