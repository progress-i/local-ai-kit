"""Data-only model modules and per-model user settings. No executable plugins."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

from .common import LOCK, atomic_json, digest, download

MODEL_ALIAS = "local-ai"
ENGINE_SETTINGS = {"model", "context", "threads", "batch", "ubatch", "cache_ram",
                   "ctx_checkpoints", "reasoning", "reasoning_budget"}
INTEGER_LIMITS = {"context": (512, 131072), "threads": (1, 256), "batch": (1, 2048),
                  "ubatch": (1, 512), "cache_ram": (0, 1024), "ctx_checkpoints": (0, 8),
                  "max_tokens": (16, 16384), "reasoning_budget": (0, 8192)}
SETTING_KEYS = set(INTEGER_LIMITS) | {"temperature", "reasoning"}


def validate_settings(module, values):
    if not isinstance(values, dict) or set(values) != SETTING_KEYS:
        raise ValueError("Неверный набор параметров модели.")
    for key, (low, high) in INTEGER_LIMITS.items():
        value = values[key]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{key}: требуется целое число от {low} до {high}.")
    if values["context"] > module["context_limit"]:
        raise ValueError(f"Контекст этого модуля ограничен {module['context_limit']} токенами.")
    temperature = values["temperature"]
    if (type(temperature) not in (int, float) or not math.isfinite(temperature)
            or not 0 <= temperature <= 2):
        raise ValueError("Температура: число от 0 до 2.")
    if type(values["reasoning"]) is not bool:
        raise ValueError("Рассуждения: требуется true или false.")
    if values["reasoning"] and not module["capabilities"]["reasoning"]:
        raise ValueError("Этот модуль не поддерживает рассуждения.")
    if values["ubatch"] > values["batch"]:
        raise ValueError("ubatch не должен превышать batch.")
    if values["max_tokens"] + 128 >= values["context"]:
        raise ValueError("Уменьшите лимит генерации: в контексте должно остаться место для запроса.")
    if values["reasoning"] and values["reasoning_budget"] >= values["max_tokens"]:
        raise ValueError("Бюджет рассуждений должен быть меньше общего лимита генерации.")
    return dict(values)


def validate_module(module):
    required = {"id", "name", "engine", "file", "url", "sha256", "size", "capabilities",
                "context_limit", "min_free_gib", "defaults"}
    if not isinstance(module, dict) or set(module) != required:
        raise ValueError("Модуль: требуется полный набор полей из образца Qwen в locks/versions.json.")
    if not isinstance(module["id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", module["id"]):
        raise ValueError("ID модуля: до 64 латинских букв в нижнем регистре, цифр, точек, дефисов.")
    if not isinstance(module["name"], str) or not 1 <= len(module["name"].strip()) <= 100:
        raise ValueError("Модуль: неверное название.")
    if module["engine"] != "llama.cpp":
        raise ValueError("Поддерживается движок llama.cpp, закреплённый в этом комплекте.")
    if not isinstance(module["file"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.gguf", module["file"], re.I):
        raise ValueError("Файл модели: простое имя .gguf без пути.")
    if not isinstance(module["url"], str):
        raise ValueError("Модуль: требуется HTTPS URL.")
    url = urlsplit(module["url"])
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
        raise ValueError("Модуль: требуется HTTPS URL без пароля и фрагмента.")
    if not isinstance(module["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", module["sha256"]):
        raise ValueError("Модуль: требуется SHA-256 из 64 строчных шестнадцатеричных символов.")
    if type(module["size"]) is not int or not 0 < module["size"] <= 1024**4:
        raise ValueError("Модуль: неверный размер файла в байтах.")
    if (not isinstance(module["capabilities"], dict) or set(module["capabilities"]) != {"tools", "reasoning"}
            or any(type(v) is not bool for v in module["capabilities"].values())):
        raise ValueError("Модуль: capabilities должен содержать tools и reasoning: true/false.")
    if type(module["context_limit"]) is not int or not 512 <= module["context_limit"] <= 131072:
        raise ValueError("Модуль: context_limit от 512 до 131072.")
    ram = module["min_free_gib"]
    if type(ram) not in (int, float) or not math.isfinite(ram) or not 0 < ram <= 1024:
        raise ValueError("Модуль: неверный min_free_gib.")
    validate_settings(module, module["defaults"])
    return module


def catalog(root):
    modules = {}
    for ident, module in LOCK["models"]["modules"].items():
        validate_module(module)
        if ident != module["id"]:
            raise ValueError("ID модуля не совпал с ключом в locks/versions.json.")
        modules[ident] = module
    folder = root / "data/model-modules"
    if folder.is_symlink() or folder.resolve() != folder:
        raise ValueError("Папка модулей не должна быть ссылкой.")
    for path in sorted(folder.glob("*.json")):
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError(f"Некорректный модуль: {path.name}.")
        module = validate_module(json.loads(path.read_text(encoding="utf-8")))
        if module["id"] in modules:
            raise ValueError(f"Повторный ID модуля: {module['id']}.")
        modules[module["id"]] = module
    files = [m["file"].casefold() for m in modules.values()]
    if len(files) != len(set(files)):
        raise ValueError("У разных модулей должны быть разные имена GGUF-файлов.")
    return modules


def add_module(root, module):
    module = validate_module(module)
    modules = catalog(root)
    if module["id"] in modules or any(m["file"].casefold() == module["file"].casefold() for m in modules.values()):
        raise ValueError("Модуль с таким ID или именем файла уже существует.")
    path = root / "data/model-modules" / (module["id"] + ".json")
    atomic_json(path, module)
    return module


def model_path(root, module):
    path = root / "models" / module["file"]
    if path.is_symlink() or path.parent.resolve() != path.parent:
        raise ValueError("Папка моделей и GGUF не должны быть ссылками/junction.")
    return path


def model_present(root, module):
    path = model_path(root, module)
    return path.is_file() and path.stat().st_size == module["size"]


def ensure_model(root, module, *, allow_download):
    path = model_path(root, module)
    if not path.exists() and not allow_download:
        raise ValueError(f"Модель {module['name']} не скачана. Выполните install --model {module['id']}.")
    if allow_download:
        download(root, "model/" + module["id"], path, item=module)
    elif not model_present(root, module) or digest(path) != module["sha256"]:
        raise ValueError(f"Размер или SHA-256 модели не совпал: {path}.")
    return path


def preferences(root):
    path = root / "data/settings.json"
    if not path.exists():
        return {"schema": 1, "model": LOCK["models"]["default"], "profiles": {}}
    if path.is_symlink() or path.parent.resolve() != path.parent:
        raise ValueError("Файл настроек не должен быть ссылкой.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != 1 or not isinstance(value.get("profiles"), dict):
        raise ValueError("Неверный формат data/settings.json.")
    return value


def selected_settings(root, ident=None):
    saved = preferences(root)
    ident = ident or saved["model"]
    modules = catalog(root)
    if ident not in modules:
        raise ValueError(f"Модуль не найден: {ident}.")
    module = modules[ident]
    values = validate_settings(module, saved["profiles"].get(ident, module["defaults"]))
    return {"model": ident, **values}


def save_settings(root, values):
    modules = catalog(root)
    values = dict(values)
    ident = values.pop("model")
    validate_settings(modules[ident], values)
    saved = preferences(root)
    saved["model"] = ident
    saved["profiles"][ident] = values
    atomic_json(root / "data/settings.json", saved)
