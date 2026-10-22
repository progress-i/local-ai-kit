# 3. Изолированные инструменты

Остановите запущенный проект через `Ctrl+C`.

## Ubuntu

### 1. Открыть папку программы и задать кэш проекта

```bash
cd "$HOME/local-ai-kit/app"
export TMPDIR="$HOME/LocalAISeries/tmp"
export XDG_CACHE_HOME="$HOME/LocalAISeries/cache/xdg"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME"
```

### 2. Установить Wasmtime 49.0.0

Wasmtime запускает файловые инструменты в WASI с доступом к `LocalAISeries/data/workspace`. Файл `locks/agent-linux.txt` для Ubuntu или `locks/agent-windows.txt` для Windows закрепляет версию и SHA-256.

```bash
"$HOME/LocalAISeries/env/bin/python" -m pip --isolated install --require-hashes --only-binary=:all: --no-input --disable-pip-version-check --cache-dir "$HOME/LocalAISeries/cache/pip" -r "$HOME/local-ai-kit/locks/agent-linux.txt" &&
"$HOME/LocalAISeries/env/bin/python" -m pip --isolated check
```

### 3. Проверить изоляцию и записать готовность третьего этапа

Проверка пытается выйти из рабочей папки и перезаписать существующий файл. Оба действия должны быть отклонены.

```bash
"$HOME/LocalAISeries/env/bin/python" -B - <<'PY'
from pathlib import Path
from lib.common import owned_root
root = owned_root(Path.home() / 'LocalAISeries')
from lib.sandbox import security_check
from manage import read_state, installed_packages
workspace = root / 'data/workspace'
workspace.mkdir(parents=True, exist_ok=True)
result = security_check(workspace)
assert result['raw_traversal'] == 'PASS'
assert result['no_overwrite'] == 'PASS'
print(result)
state = read_state(root)
state['stage'] = max(state['stage'], 3)
installed_packages(root, state)
print('STAGE 3: OK')
PY
```

`raw_traversal: PASS` — WASI отклонил выход из папки. `no_overwrite: PASS` — существующий файл защищён от перезаписи.

### 4. Запустить помощника на CPU

Команда запуска использует установленные файлы из `LocalAISeries`.

```bash
bash "$HOME/local-ai-kit/local-ai.sh" start --stage 3
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

### 2. Установить Wasmtime 49.0.0

Wasmtime запускает файловые инструменты в WASI с доступом к `LocalAISeries/data/workspace`. Файл `locks/agent-linux.txt` для Ubuntu или `locks/agent-windows.txt` для Windows закрепляет версию и SHA-256.

```powershell
& "$HOME/LocalAISeries/env/Scripts/python.exe" -m pip --isolated install --require-hashes '--only-binary=:all:' --no-input --disable-pip-version-check --cache-dir "$HOME/LocalAISeries/cache/pip" -r "$HOME/local-ai-kit/locks/agent-windows.txt"
if ($LASTEXITCODE) { throw 'pip: установка не завершена' }
& "$HOME/LocalAISeries/env/Scripts/python.exe" -m pip --isolated check
if ($LASTEXITCODE) { throw 'pip: зависимости несовместимы' }
```

### 3. Проверить изоляцию и записать готовность третьего этапа

Проверка пытается выйти из рабочей папки и перезаписать существующий файл. Оба действия должны быть отклонены.

```powershell
& "$HOME/LocalAISeries/env/Scripts/python.exe" -B -c @'
from pathlib import Path
from lib.common import owned_root
root = owned_root(Path.home() / 'LocalAISeries')
from lib.sandbox import security_check
from manage import read_state, installed_packages
workspace = root / 'data/workspace'
workspace.mkdir(parents=True, exist_ok=True)
result = security_check(workspace)
assert result['raw_traversal'] == 'PASS'
assert result['no_overwrite'] == 'PASS'
print(result)
state = read_state(root)
state['stage'] = max(state['stage'], 3)
installed_packages(root, state)
print('STAGE 3: OK')
'@
if ($LASTEXITCODE) { throw 'Python: ошибка выполнения' }
```

`raw_traversal: PASS` — WASI отклонил выход из папки. `no_overwrite: PASS` — существующий файл защищён от перезаписи.

### 4. Запустить помощника на CPU

Команда запуска использует установленные файлы из `LocalAISeries`.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& "$HOME/local-ai-kit/local-ai.ps1" start -Stage 3
```

## Запустить с готовой сборкой Vulkan

После `Ctrl+C` выполните команду своей ОС.

### 1. Ubuntu

```bash
bash "$HOME/local-ai-kit/local-ai.sh" start --stage 3 --backend vulkan
```

### 2. Windows

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& "$HOME/local-ai-kit/local-ai.ps1" start -Stage 3 -Backend vulkan
```

## Создание заметки

Для повторной записи выберите новое имя: инструмент создаёт только новые файлы.

1. Создайте новый диалог и включите «Инструменты».
2. Отправьте: «Вызови write_note: создай файл plan-01.txt с точным текстом: Проверить документы проекта Сапфир. Затем прочитай этот файл через read_note.»
3. В окне подтверждения проверьте имя и текст → «Разрешить».
4. Откройте журнал «Операции инструментов».

Ожидаемый результат: успешные `write_note` и `read_note`; файл `LocalAISeries/data/workspace/plan-01.txt` содержит заданный текст.

## Отклонение записи

В новом диалоге запросите создание `denied-01.txt`. Нажмите «Отклонить».

Ожидаемый результат: `denied-01.txt` отсутствует.

## Автоматическая установка

Распакуйте проект в папку `local-ai-kit` внутри домашней папки. Перед установкой остановите работающий чат через `Ctrl+C`.

### Ubuntu

Установка:

```bash
bash "$HOME/local-ai-kit/local-ai.sh" install --stage 3 --backend cpu
```

Запуск:

```bash
bash "$HOME/local-ai-kit/local-ai.sh" start --stage 3 --backend cpu
```

### Windows

Откройте 64-разрядный PowerShell. При блокировке Smart App Control его необходимо отключить. Microsoft Defender оставьте включённым.

Установка:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& "$HOME\local-ai-kit\local-ai.ps1" install -Stage 3 -Backend cpu
```

Запуск в том же окне:

```powershell
& "$HOME\local-ai-kit\local-ai.ps1" start -Stage 3 -Backend cpu
```

`Stage 3` — третий этап; `Backend cpu` — вычисления на процессоре. После запуска откроется чат в браузере. Остановка — `Ctrl+C`.
