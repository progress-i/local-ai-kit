# 2. Документы и память

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

### 2. Подключить документы и память

Зависимости уже установлены в первом этапе. Блок записывает готовность второго этапа.

```bash
"$HOME/LocalAISeries/env/bin/python" -B - <<'PY'
from pathlib import Path
from lib.common import owned_root
root = owned_root(Path.home() / 'LocalAISeries')
from manage import read_state, installed_packages
state = read_state(root)
state['stage'] = max(state['stage'], 2)
installed_packages(root, state)
print('STAGE 2: OK')
PY
```

### 3. Создать документ для проверки

Файл сохраняется в `LocalAISeries/data/sapphire.txt`.

```bash
cat > "$HOME/LocalAISeries/data/sapphire.txt" <<'TEXT'
Проект: Сапфир.
Код доступа: 4182.
Срок подготовки: пятница.
TEXT
```

### 4. Запустить помощника на CPU

Команда запуска использует установленные файлы из `LocalAISeries`.

```bash
bash "$HOME/local-ai-kit/local-ai.sh" start --stage 2
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

### 2. Подключить документы и память

Зависимости уже установлены в первом этапе. Блок записывает готовность второго этапа.

```powershell
& "$HOME/LocalAISeries/env/Scripts/python.exe" -B -c @'
from pathlib import Path
from lib.common import owned_root
root = owned_root(Path.home() / 'LocalAISeries')
from manage import read_state, installed_packages
state = read_state(root)
state['stage'] = max(state['stage'], 2)
installed_packages(root, state)
print('STAGE 2: OK')
'@
if ($LASTEXITCODE) { throw 'Python: ошибка выполнения' }
```

### 3. Создать документ для проверки

Файл сохраняется в `LocalAISeries/data/sapphire.txt`.

```powershell
@'
Проект: Сапфир.
Код доступа: 4182.
Срок подготовки: пятница.
'@ | Set-Content "$HOME/LocalAISeries/data/sapphire.txt" -Encoding UTF8
```

### 4. Запустить помощника на CPU

Команда запуска использует установленные файлы из `LocalAISeries`.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& "$HOME/local-ai-kit/local-ai.ps1" start -Stage 2
```

## Запустить с готовой сборкой Vulkan

После `Ctrl+C` выполните команду своей ОС.

### 1. Ubuntu

```bash
bash "$HOME/local-ai-kit/local-ai.sh" start --stage 2 --backend vulkan
```

### 2. Windows

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& "$HOME/local-ai-kit/local-ai.ps1" start -Stage 2 -Backend vulkan
```

## Документ и явная память

1. «Настройки»: контекст `4096`, лимит генерации `384`, рассуждения выключены → «Применить».
2. «Документы» → выберите `LocalAISeries/data/sapphire.txt` в домашней папке.
3. В «Явной памяти» введите `Мой город — Томск. Отвечай кратко.` → «Сохранить».
4. Создайте новый диалог. Отправьте: «Какой код проекта Сапфир указан в документе? Какой мой город?».

Ожидаемый результат: `4182` и `Томск`.

Остановите проект через `Ctrl+C`, повторите команду запуска и откройте сохранённый диалог.

## Автоматическая установка

Распакуйте проект в папку `local-ai-kit` внутри домашней папки. Перед установкой остановите работающий чат через `Ctrl+C`.

### Ubuntu

Установка:

```bash
bash "$HOME/local-ai-kit/local-ai.sh" install --stage 2 --backend cpu
```

Запуск:

```bash
bash "$HOME/local-ai-kit/local-ai.sh" start --stage 2 --backend cpu
```

### Windows

Откройте 64-разрядный PowerShell. При блокировке Smart App Control его необходимо отключить. Microsoft Defender оставьте включённым.

Установка:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& "$HOME\local-ai-kit\local-ai.ps1" install -Stage 2 -Backend cpu
```

Запуск в том же окне:

```powershell
& "$HOME\local-ai-kit\local-ai.ps1" start -Stage 2 -Backend cpu
```

`Stage 2` — второй этап; `Backend cpu` — вычисления на процессоре. После запуска откроется чат в браузере. Остановка — `Ctrl+C`.
