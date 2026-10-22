"""Shared standard-library helpers. No package installation on the host Python."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
import uuid

APP = Path(__file__).resolve().parents[1]
KIT = APP.parent
LOCK = json.loads((KIT / "locks/versions.json").read_text(encoding="utf-8"))
PROJECT = "local-ai-youtube-2026-v1"
PLATFORM = "windows" if os.name == "nt" else "linux"


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".new")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def canonical_root(value: str | Path) -> Path:
    original = Path(value).expanduser().absolute()
    if original.is_symlink() or original.resolve() != original:
        raise RuntimeError("Корень проекта и его родители не должны быть ссылками/junction.")
    root = original.resolve()
    if root in (Path.home().resolve(), Path(root.anchor)) or len(root.parts) < 3:
        raise RuntimeError("Небезопасный корень проекта.")
    if KIT == root or root in KIT.parents:
        raise RuntimeError("Папка установки должна находиться отдельно от распакованного комплекта.")
    return root


def owned_root(value, create=False) -> Path:
    root = canonical_root(value)
    marker = root / "project.json"
    if marker.exists():
        m = json.loads(marker.read_text(encoding="utf-8-sig"))
        if m.get("project") != PROJECT or Path(m.get("root", "")) != root:
            raise RuntimeError("Маркер проекта не совпадает с этой папкой.")
    elif create:
        if root.exists() and any(root.iterdir()):
            raise RuntimeError(f"Папка уже содержит чужие файлы: {root}")
        root.mkdir(parents=True, exist_ok=True)
        atomic_json(marker, {"project": PROJECT, "root": str(root), "id": uuid.uuid4().hex})
    else:
        raise RuntimeError(f"Здесь нет установленного проекта: {root}")
    return root


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def http_json(port, route, body=None, timeout=600):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(f"http://127.0.0.1:{port}{route}",
                                     data=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
                                     headers={"Content-Type": "application/json"})
    with opener.open(request, timeout=timeout) as response:
        return json.load(response)


def download(root: Path, key: str, destination: Path | None = None, *, item=None) -> Path:
    item = LOCK["artifacts"][key] if item is None else item
    destination = destination or root / "cache/downloads" / (key + ".download")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        if digest(destination) == item["sha256"]:
            print(f"SHA256 OK: {key}", flush=True)
            return destination
        raise RuntimeError(f"SHA256 не совпал: {destination}. Удалите только этот файл и повторите.")
    part = destination.with_name(destination.name + ".part")
    print(f"Загрузка {key} ({item.get('size', 0) / 1e6:.1f} MB)...", flush=True)
    for attempt in range(1, 4):
        try:
            offset = part.stat().st_size if part.exists() else 0
            headers = {"User-Agent": "LocalAISeries/1.0", "Accept-Encoding": "identity"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            request = urllib.request.Request(item["url"], headers=headers)
            with urllib.request.urlopen(request, timeout=90) as response:
                resume = response.status == 206
                if resume and not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                    raise RuntimeError("Сервер вернул неправильный диапазон загрузки.")
                with part.open("ab" if resume else "wb") as f:
                    mark = time.monotonic()
                    while True:
                        block = response.read(4 * 1024 * 1024)
                        if not block:
                            break
                        f.write(block)
                        if time.monotonic() - mark > 10:
                            print(f"  {f.tell() / 1e6:.0f} MB", flush=True)
                            mark = time.monotonic()
            if item.get("size") and part.stat().st_size != item["size"]:
                raise RuntimeError("Загрузка неполная.")
            if digest(part) != item["sha256"]:
                part.unlink()
                raise RuntimeError(f"SHA256 не совпал: {key}; загрузка отброшена.")
            os.replace(part, destination)
            print(f"SHA256 OK: {key}", flush=True)
            return destination
        except urllib.error.HTTPError as e:
            if e.code == 416 and part.exists():
                if digest(part) == item["sha256"]:
                    os.replace(part, destination)
                    return destination
                part.unlink()
            if attempt == 3:
                raise
            print(f"Загрузка: попытка {attempt}/3: HTTP {e.code}", flush=True)
        except (OSError, TimeoutError) as e:
            if attempt == 3:
                raise
            print(f"Загрузка: попытка {attempt}/3: {e}", flush=True)
    raise RuntimeError("Не удалось завершить загрузку.")


def unpack(archive: Path, target: Path, strip_top=False):
    """Extract verified source/runtime archives into an empty staging directory."""
    stage = target.with_name(target.name + ".extracting")
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    with tarfile.open(archive) as tf:
        # CPython 3.12 data filter also checks symlink destinations.
        if hasattr(tarfile, "data_filter"):
            tf.extractall(stage, filter="data")
        else:
            # Only the Ubuntu bootstrap may use Python 3.10/3.11.
            for m in tf.getmembers():
                dest = (stage / m.name).resolve()
                if stage.resolve() not in dest.parents:
                    raise RuntimeError("Небезопасный путь в архиве.")
                if m.issym() or m.islnk():
                    link = ((dest.parent if m.issym() else stage) / m.linkname).resolve()
                    if stage.resolve() not in link.parents:
                        raise RuntimeError("Небезопасная ссылка в архиве.")
                elif not (m.isfile() or m.isdir()):
                    raise RuntimeError("Неожиданный тип файла в архиве.")
            tf.extractall(stage)
    source = stage
    if strip_top:
        children = list(stage.iterdir())
        if len(children) != 1 or not children[0].is_dir():
            raise RuntimeError("Неожиданная структура архива.")
        source = children[0]
    if target.exists():
        shutil.rmtree(target)
    source.rename(target)
    if stage.exists():
        shutil.rmtree(stage)


def project_env(root: Path):
    env = os.environ.copy()
    directories = {
        "PIP_CACHE_DIR": "cache/pip", "XDG_CACHE_HOME": "cache/xdg",
        "HF_HOME": "cache/huggingface", "MPLCONFIGDIR": "cache/matplotlib",
        "TMPDIR": "tmp", "TEMP": "tmp", "TMP": "tmp",
        "PYTHONPYCACHEPREFIX": "cache/pycache",
    }
    for name, relative in directories.items():
        p = root / relative
        p.mkdir(parents=True, exist_ok=True)
        env[name] = str(p)
    env.update(PYTHONNOUSERSITE="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1",
               PIP_CONFIG_FILE=os.devnull, CMAKE_BUILD_PARALLEL_LEVEL="1", OMP_NUM_THREADS="4")
    for k in list(env):
        if k.startswith("LLAMA_ARG_") or k in ("PYTHONPATH", "PYTHONHOME"):
            env.pop(k, None)
    if PLATFORM == "windows":
        env["PATH"] = str(root / "env/Scripts") + os.pathsep + str(root / "python") + os.pathsep + env.get("PATH", "")
    return env


def execute(argv, root: Path, *, capture=False, timeout=None, env=None, **kwargs):
    argv = [str(x) for x in argv]
    result = subprocess.run(argv, env=env or project_env(root), check=False,
                            capture_output=capture, text=True, encoding="utf-8", errors="replace",
                            timeout=timeout, **kwargs)
    if result.returncode:
        detail = (result.stdout + result.stderr)[-6000:] if capture else "Смотрите вывод команды выше."
        raise RuntimeError(f"Команда завершилась с кодом {result.returncode}: {argv[0]}\n{detail}")
    return result


def env_python(root: Path) -> Path:
    return root / ("env/Scripts/python.exe" if PLATFORM == "windows" else "env/bin/python")


def bootstrap(root: Path) -> Path:
    runtime = root / "python"
    binary = runtime / ("python.exe" if PLATFORM == "windows" else "bin/python3")
    if not binary.exists():
        archive = download(root, "python-" + PLATFORM)
        unpack(archive, runtime, strip_top=True)
    directory = root / "env"
    if directory.is_symlink() or directory.resolve() != directory:
        raise RuntimeError("Папка окружения не должна быть ссылкой/junction.")
    py = env_python(root)
    ready = False
    if py.exists():
        try:
            probe = subprocess.run([str(py), "-B", "-I", "-m", "pip", "--version"],
                                   env=project_env(root), capture_output=True, timeout=30)
            ready = probe.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not ready:
        print("Подготовка Python-окружения…", flush=True)
        execute([binary, "-B", "-m", "venv", "--clear", directory], root)
    return py
