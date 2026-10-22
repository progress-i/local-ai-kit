[CmdletBinding()]
param(
    [Parameter(Position=0)][ValidateSet('install','start','check','hardware','inventory','remove')][string]$Action='hardware',
    [ValidateRange(0,4)][int]$Stage=0,
    [ValidateSet('cpu','vulkan')][string]$Backend='cpu',
    [string]$Device='Vulkan0',
    [string]$Model='',
    [string]$Root=(Join-Path $HOME 'LocalAISeries'),
    [switch]$NoBrowser,
    [switch]$Offline,
    [switch]$Voice
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$SavedNoBytecode=$env:PYTHONDONTWRITEBYTECODE
$env:PYTHONDONTWRITEBYTECODE='1'
$KitDir=$PSScriptRoot
$ProjectName='local-ai-youtube-2026-v1'
$Root=[IO.Path]::GetFullPath($Root).TrimEnd('\')

function Assert-Root {
    if ($Root -eq [IO.Path]::GetPathRoot($Root).TrimEnd('\') -or $Root -eq $HOME.TrimEnd('\') -or $Root -eq $KitDir) { throw 'Небезопасная папка установки.' }
    if ($KitDir.StartsWith($Root+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Папка комплекта находится внутри папки установки.' }
    $partPath=Split-Path $Root -Parent
    while ($partPath) {
        if (Test-Path -LiteralPath $partPath) {
            $part=Get-Item -LiteralPath $partPath
            if ($part.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Родитель папки установки является ссылкой/junction.' }
        }
        $nextPath=Split-Path $partPath -Parent
        if ($nextPath -eq $partPath) { break }
        $partPath=$nextPath
    }
    if (Test-Path -LiteralPath $Root) {
        if ((Get-Item -LiteralPath $Root).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Корень проекта является ссылкой/junction.' }
    }
    $marker=Join-Path $Root 'project.json'
    if (Test-Path -LiteralPath $marker) {
        $m=Get-Content -LiteralPath $marker -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($m.project -ne $ProjectName -or $m.root -ne $Root) { throw 'Маркер проекта не совпал.' }
    } elseif ($Action -eq 'install') {
        if ((Test-Path -LiteralPath $Root) -and @(Get-ChildItem -LiteralPath $Root -Force).Count) { throw 'Папка уже содержит чужие файлы.' }
        New-Item -ItemType Directory -Path $Root -Force | Out-Null
        @{project=$ProjectName;root=$Root;id=[guid]::NewGuid().ToString('N')} | ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding UTF8
    } elseif ($Action -ne 'hardware') { throw 'Проект не установлен в этой папке.' }
}

function Invoke-Native([string]$File,[string[]]$Arguments) {
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Команда $File завершилась с кодом $LASTEXITCODE" }
}

function Get-OwnedPaths([string]$Path) {
    foreach ($entry in (Get-ChildItem -LiteralPath $Path -Force)) {
        $entry.FullName
        if ($entry.PSIsContainer -and -not ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            Get-OwnedPaths $entry.FullName
        }
    }
}

function Remove-OwnedTree([string]$Path) {
    $entry=Get-Item -LiteralPath $Path -Force
    if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        if ($entry.PSIsContainer) { [IO.Directory]::Delete($Path,$false) } else { [IO.File]::Delete($Path) }
    } elseif ($entry.PSIsContainer) {
        foreach ($child in (Get-ChildItem -LiteralPath $Path -Force)) { Remove-OwnedTree $child.FullName }
        [IO.Directory]::Delete($Path,$false)
    } else {
        [IO.File]::SetAttributes($Path,[IO.FileAttributes]::Normal)
        [IO.File]::Delete($Path)
    }
}

try {
    if (-not [Environment]::Is64BitProcess) { throw 'Откройте 64-разрядный Windows PowerShell или PowerShell 7.' }
    if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { throw 'Комплект рассчитан на Windows x64, Intel/AMD.' }
    if ($Action -eq 'hardware') {
        Get-CimInstance Win32_Processor | Select-Object -Property @('Name','NumberOfCores','NumberOfLogicalProcessors')
        Get-CimInstance Win32_ComputerSystem | Select-Object -Property @{n='TotalRAM_GiB';e={[math]::Round($_.TotalPhysicalMemory/1073741824,2)}}
        Get-CimInstance Win32_OperatingSystem | Select-Object -Property @('Caption',@{n='FreeRAM_GiB';e={[math]::Round($_.FreePhysicalMemory/1048576,2)}})
        Get-CimInstance Win32_VideoController | Select-Object -Property @('Name','DriverVersion')
        Write-Host 'CPU: основной путь. Vulkan: после проверки драйвера; NVIDIA/AMD/Intel. NPU не используется.'
        $HardwarePython=Join-Path $Root 'env/Scripts/python.exe'
        if (Test-Path -LiteralPath $HardwarePython) { Invoke-Native $HardwarePython @('-B',(Join-Path $KitDir 'app/manage.py'),'--root',$Root,'hardware') }
        exit 0
    }
    Assert-Root
    if ($Action -in @('start','check') -and -not (Test-Path -LiteralPath (Join-Path $Root 'env/Scripts/python.exe'))) {
        throw 'Окружение не установлено полностью. Повторите install.'
    }
    if ($Action -eq 'inventory') {
        Get-ChildItem -LiteralPath $Root -Force | Select-Object -Property @('Name','Mode')
        $receipt=Join-Path $Root 'state/receipt.json'
        if (Test-Path -LiteralPath $receipt) { Get-Content -LiteralPath $receipt -Raw -Encoding UTF8 | Write-Host }
        exit 0
    }
    # Removal runs outside the private interpreter, so Windows can delete its DLLs.
    if ($Action -eq 'remove') {
        $marker=Join-Path $Root 'project.json'
        $receipt=Join-Path $Root 'state/receipt.json'
        $known=@('project.json','python','env','cache','tmp','state','tools','src','build','models','data','logs','browser','browser-firefox')
        $unknown=@(Get-ChildItem -LiteralPath $Root -Force | Where-Object { $_.Name -notin $known -and -not $_.Name.EndsWith('.extracting') })
        if ($unknown.Count) { throw ('В корне найдены неучтённые файлы. Сначала перенесите их: '+(($unknown | Select-Object -ExpandProperty Name) -join ', ')) }
        Write-Host "Удаление всей выделенной папки: $Root"
        Get-ChildItem -LiteralPath $Root -Force | Select-Object -Property @('Name','Mode')
        $fileInventory=Join-Path $Root 'state/file-inventory.txt'
        New-Item -ItemType Directory -Path (Split-Path $fileInventory -Parent) -Force | Out-Null
        Get-OwnedPaths $Root | Set-Content -LiteralPath $fileInventory -Encoding UTF8
        Write-Host "Полный список путей: $fileInventory"
        if (Test-Path -LiteralPath $receipt) { Get-Content -LiteralPath $receipt -Raw -Encoding UTF8 | Write-Host }
        $allProcesses=@(Get-CimInstance Win32_Process)
        $browserPattern='--(?:user-data-dir=|profile\s+)"?'+[regex]::Escape($Root)+'\\browser(?:-firefox)?(?:["\s]|$)'
        $projectProcesses=@($allProcesses | Where-Object {
            $_.ExecutablePath -and ($_.ExecutablePath.StartsWith($Root+'\',[StringComparison]::OrdinalIgnoreCase)) -or
            ($_.CommandLine -and $_.CommandLine -match $browserPattern)
        })
        $processIds=@($projectProcesses | Select-Object -ExpandProperty ProcessId)
        do {
            $children=@($allProcesses | Where-Object { $_.ParentProcessId -in $processIds -and $_.ProcessId -notin $processIds })
            $projectProcesses+= $children
            $processIds=@($projectProcesses | Select-Object -ExpandProperty ProcessId)
        } while ($children.Count)
        $projectProcesses | Select-Object -Property @('ProcessId','Name','ExecutablePath')
        $confirm=Read-Host 'Введите DELETE для удаления перечисленного'
        if ($confirm -cne 'DELETE') { Write-Host 'Удаление отменено.'; exit 0 }
        [array]::Reverse($projectProcesses)
        foreach ($p in $projectProcesses) {
            $now=Get-CimInstance Win32_Process -Filter "ProcessId=$($p.ProcessId)" -ErrorAction SilentlyContinue
            if ($now -and $now.CreationDate -eq $p.CreationDate -and $now.ExecutablePath -eq $p.ExecutablePath) { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop }
        }
        Set-Location -LiteralPath (Split-Path $Root -Parent)
        Remove-OwnedTree $Root
        if (Test-Path -LiteralPath $Root) { throw 'Папка удалена не полностью.' }
        Write-Host 'Удалено. Общие драйверы, браузер и чужие программы сохранены.'
        exit 0
    }
    $SavedTemp=$env:TEMP; $SavedTmp=$env:TMP
    $env:TEMP=Join-Path $Root 'tmp'; $env:TMP=$env:TEMP
    New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
    $Python=Join-Path $Root 'python/python.exe'
    if (-not (Test-Path -LiteralPath $Python)) {
        $lock=Get-Content -LiteralPath (Join-Path $KitDir 'locks/versions.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $item=$lock.artifacts.'python-windows'
        $cache=Join-Path $Root 'cache/downloads'
        New-Item -ItemType Directory -Path $cache -Force | Out-Null
        $archive=Join-Path $cache 'python-windows.download'
        if (-not (Test-Path -LiteralPath $archive)) {
            [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
            $ProgressPreference='SilentlyContinue'
            Invoke-WebRequest -UseBasicParsing -Uri $item.url -OutFile ($archive+'.part')
            if ((Get-FileHash -LiteralPath ($archive+'.part') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.sha256) { Remove-Item -LiteralPath ($archive+'.part'); throw 'SHA256 Python не совпал.' }
            Move-Item -LiteralPath ($archive+'.part') -Destination $archive
        }
        if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.sha256) { throw 'SHA256 Python не совпал.' }
        $stageDir=Join-Path $Root 'python.extracting'
        if (Test-Path -LiteralPath $stageDir) { Remove-Item -LiteralPath $stageDir -Recurse -Force }
        New-Item -ItemType Directory -Path $stageDir | Out-Null
        Invoke-Native 'tar.exe' @('-xf',$archive,'-C',$stageDir)
        if (Test-Path -LiteralPath (Join-Path $Root 'python')) { Remove-Item -LiteralPath (Join-Path $Root 'python') -Recurse -Force }
        Move-Item -LiteralPath (Join-Path $stageDir 'python') -Destination (Join-Path $Root 'python')
        Remove-Item -LiteralPath $stageDir -Recurse -Force
    }
    $PrivatePython=Join-Path $Root 'env/Scripts/python.exe'
    if ($Action -eq 'install') {
        # Prepare/repair the venv before starting its Windows interpreter.
        Invoke-Native $Python @('-B','-c','import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from lib.common import bootstrap; bootstrap(Path(sys.argv[2]))',(Join-Path $KitDir 'app'),$Root)
    }
    $params=@('-B',(Join-Path $KitDir 'app/manage.py'),'--root',$Root,$Action)
    if ($Action -in @('install','start','check')) { $params+=@('--stage',"$Stage",'--backend',$Backend) }
    if ($Model -and $Action -in @('install','start','check')) { $params+=@('--model',$Model) }
    if ($Action -eq 'start') { $params+=@('--device',$Device); if ($NoBrowser) { $params+='--no-browser' } }
    if ($Action -eq 'check') { if ($Offline) { $params+='--offline' }; if ($Voice) { $params+='--voice' } }
    Invoke-Native $PrivatePython $params
} catch {
    Write-Error $_
    exit 1
} finally {
    $env:PYTHONDONTWRITEBYTECODE=$SavedNoBytecode
    if (Test-Path variable:SavedTemp) { $env:TEMP=$SavedTemp; $env:TMP=$SavedTmp }
}
