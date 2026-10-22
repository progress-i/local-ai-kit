"""Short acceptance checks. Failure is never converted into a claimed successful stage."""
from __future__ import annotations

import io
import json
from pathlib import Path
import re
import secrets
import time
import urllib.request
import uuid
import wave

from lib.common import LOCK, PLATFORM, digest, execute
from manage import build_environment, http_json, read_state, server_binary, whisper_binary
from lib.models import MODEL_ALIAS, catalog, model_path, selected_settings


def require(condition, label, detail=""):
    if not condition:
        raise RuntimeError(f"FAIL {label}: {detail}")
    print(f"PASS {label}" + (f": {detail}" if detail else ""), flush=True)


def basic_offline(root, stage, model=None):
    module = catalog(root)[selected_settings(root, model)["model"]]
    require(digest(model_path(root, module)) == module["sha256"], "MODEL_SHA256")
    binary = server_binary(root, "cpu")
    output = execute([binary, "--help"], root, capture=True, env=build_environment(root)).stdout
    for flag in ("--device", "--gpu-layers", "--ctx-size", "--parallel", "--jinja", "--reasoning", "--cache-ram", "--ctx-checkpoints"):
        require(flag in output, "FLAG " + flag)
    if stage >= 3:
        from lib.sandbox import security_check
        result = security_check(root / "data/workspace")
        require(result["raw_traversal"] == "PASS", "WASI_BOUNDARY", json.dumps(result, ensure_ascii=False))
    if stage >= 4:
        for key, name in (("whisper-model", "ggml-base.bin"), ("piper-model", "ru_RU-denis-medium.onnx"),
                          ("piper-config", "ru_RU-denis-medium.onnx.json")):
            require(digest(root / "models" / name) == LOCK["artifacts"][key]["sha256"], "SHA256 " + name)
        require(whisper_binary(root).exists(), "WHISPER_BUILT")


def api_check():
    require(http_json(8081, "/health")["status"] == "ok", "LLAMA_HEALTH")
    models = http_json(8081, "/v1/models")["data"]
    require(any(m["id"] == MODEL_ALIAS for m in models), "MODEL_ALIAS")
    nonce = secrets.token_hex(3)
    messages = [{"role": "user", "content": f"Запомни мой код: {nonce}. Ответь кратко."}]
    base = {"model": MODEL_ALIAS, "max_tokens": 96, "temperature": 0, "stream": False, "reasoning_effort": "none"}
    first = http_json(8081, "/v1/chat/completions", {**base, "messages": messages})["choices"][0]["message"]
    messages.append({"role": "assistant", "content": first.get("content") or "Код сохранён."})
    messages.append({"role": "user", "content": "Какой код я просил запомнить? Напиши сам код."})
    second = http_json(8081, "/v1/chat/completions", {**base, "messages": messages})
    text = second["choices"][0]["message"].get("content") or ""
    require(re.search(r"(?<![a-z0-9])" + re.escape(nonce) + r"(?![a-z0-9])", text, re.I) is not None, "MULTITURN", text[:200])
    print("TIMINGS:", json.dumps(second.get("timings", second.get("usage", {})), ensure_ascii=False))


def backend_check(root, backend):
    launch = json.loads((root / "state/launch.json").read_text())
    require(launch["backend"] == backend, "REQUESTED_BACKEND", backend)
    import psutil
    process = psutil.Process(launch["pid"])
    require(process.create_time() == launch["create_time"] and Path(process.exe()) == server_binary(root, backend), "SERVER_PROCESS_OWNERSHIP")
    argv = launch["argv"]
    log = (root / "logs/llama-server.log").read_text(errors="replace")
    if backend == "cpu":
        require(argv[argv.index("--device") + 1] == "none" and argv[argv.index("--gpu-layers") + 1] == "0", "CPU_ONLY")
    else:
        offloads = re.findall(r"offloaded\s+(\d+)(?:/\d+)?\s+layers?", log, re.I)
        require(any(int(n) > 0 for n in offloads), "GPU_LAYERS_OFFLOADED", ", ".join(offloads) or "в журнале нет перенесённых слоёв")
        require(launch["device"] in log and re.search(r"Vulkan\d+.*(?:model|compute).*buffer|(?:model|compute).*Vulkan\d+.*buffer", log, re.I),
                "GPU_BUFFERS", "В журнале есть буферы модели/вычислений на Vulkan GPU")
        from lib.gpu import engine_snapshot, nvidia_activity, nvidia_monitor
        before = engine_snapshot(launch["pid"])
        monitor = nvidia_monitor()
        try:
            http_json(8081, "/v1/chat/completions", {"model": MODEL_ALIAS, "max_tokens": 128, "temperature": 0,
                      "messages": [{"role": "user", "content": "Перечисли числа от 1 до 200, разделяя их пробелами."}]})
        finally:
            nvidia_used = nvidia_activity(monitor, launch["pid"])
        after = engine_snapshot(launch["pid"])
        delta = sum(max(0, value - before.get(key, 0)) for key, value in after.items())
        require(delta > 0 or nvidia_used, "GPU_EXECUTION_COUNTER",
                f"Время GPU данного PID: +{delta / 1e6:.3f} ms; NVIDIA SM: {nvidia_used}. "
                "Если драйвер не экспортирует счётчики, автоматическое подтверждение невозможно; проверьте Compute именно llama-server в мониторе GPU.")


def ui_token():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    html = opener.open("http://127.0.0.1:8080", timeout=5).read().decode()
    match = re.search(r"const TOKEN='([A-Za-z0-9_-]+)'", html)
    require(match is not None, "ASSISTANT_UI")
    return match[1]


def assistant_request(token, route, body=None):
    request = urllib.request.Request("http://127.0.0.1:8080" + route,
                                     data=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
                                     headers={"Content-Type": "application/json", "X-Local-Token": token})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=600) as r:
        return json.load(r)


def assistant_check(root):
    token = ui_token()
    initial = assistant_request(token, "/api/state")
    nonce = secrets.token_hex(3)
    docname = "check-" + nonce + ".txt"
    code = "сирень-" + secrets.token_hex(2)
    city = "Томск-" + secrets.token_hex(2)
    created = []
    try:
        assistant_request(token, "/api/memory", {"text": initial["memory"] + f"\nМой тестовый город: {city}."})
        assistant_request(token, "/api/document", {"name": docname, "text": f"Код проекта Сапфир: {code}."})
        chat = assistant_request(token, "/api/new", {})
        created.append(chat["id"])
        answer = assistant_request(token, "/api/chat", {"id": chat["id"], "text": "Какой код проекта Сапфир указан в документе? Какой мой тестовый город?", "agent": False})
        content = answer["messages"][-1].get("content") or ""
        require(code in content and city in content, "DOCUMENT_AND_MEMORY", content[:300])
        # A second instance reads actual disk data, independent of the browser and first process.
        from assistant import Assistant
        restarted = Assistant(root, 2)
        require(restarted.load(chat["id"])["messages"] == answer["messages"], "HISTORY_ON_DISK")
        new_chat = assistant_request(token, "/api/new", {})
        created.append(new_chat["id"])
        reply = assistant_request(token, "/api/chat", {"id": new_chat["id"], "text": "Назови мой тестовый город.", "agent": False})
        require(city in (reply["messages"][-1].get("content") or ""), "MEMORY_NEW_CHAT")
    finally:
        assistant_request(token, "/api/memory", {"text": initial["memory"]})
        assistant_request(token, "/api/document-delete", {"name": docname})
        for ident in created:
            (root / "data/chats" / (ident + ".json")).unlink(missing_ok=True)
    return token


def agent_check(root, token):
    from lib.sandbox import security_check
    result = security_check(root / "data/workspace")
    require(result["raw_traversal"] == "PASS", "WASI_BOUNDARY", json.dumps(result, ensure_ascii=False))
    name = "check-" + uuid.uuid4().hex[:8] + ".txt"
    expected = "Привет, локальный агент!"
    chat = assistant_request(token, "/api/new", {})
    try:
        reply = assistant_request(token, "/api/chat", {"id": chat["id"], "text": f"Вызови write_note: создай {name} с точным текстом «{expected}». Затем прочитай этот файл инструментом read_note.", "agent": True})
        require(reply.get("pending") is not None, "AGENT_REAL_TOOL_CALL", "Ожидается подтверждение записи")
        require(not (root / "data/workspace" / name).exists(), "WRITE_REQUIRES_CONFIRMATION")
        calls = reply["pending"]["calls"]
        require(any(c["function"]["name"] == "write_note" and json.loads(c["function"]["arguments"]).get("name") == name for c in calls), "CORRECT_TOOL_ARGUMENTS")
        reply = assistant_request(token, "/api/approve", {"id": chat["id"], "approved": True})
        path = root / "data/workspace" / name
        require(path.exists() and path.read_text(encoding="utf-8") == expected, "AGENT_FILE_CREATED")
        require(any(e["name"] == "read_note" and e["result"].get("text") == expected for e in reply["events"]), "AGENT_READ_EXECUTED")
    finally:
        (root / "data/workspace" / name).unlink(missing_ok=True)
        (root / "data/chats" / (chat["id"] + ".json")).unlink(missing_ok=True)


def voice_check(root):
    import audioop  # CPython 3.12 is pinned; no host audio libraries are installed.
    from lib.voice import synthesize, transcribe
    text = "Привет. Это проверка локального голоса."
    data = synthesize(root, text)
    with wave.open(io.BytesIO(data), "rb") as w:
        require(w.getnframes() > 0 and w.getnchannels() == 1 and w.getsampwidth() == 2, "PIPER_WAV")
        converted = audioop.ratecv(w.readframes(w.getnframes()), 2, 1, w.getframerate(), 16000, None)[0]
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000); out.writeframes(converted)
    result = transcribe(root, buffer.getvalue())
    require("привет" in result.lower() and "голос" in result.lower(), "PIPER_TO_WHISPER", result)
    print("Микрофон и динамики: отдельная ручная проверка в браузере; автоматический WAV-тест их не проверяет.")


def run_checks(root, args):
    installed = read_state(root)["stage"]
    stage = args.stage or installed
    require(1 <= stage <= installed, "STAGE_INSTALLED", str(stage))
    basic_offline(root, stage, getattr(args, "model", None))
    if args.offline:
        print("OFFLINE_CHECKS_OK: генерация и устройства ввода/вывода не проверялись.")
        return
    settings = selected_settings(root, getattr(args, "model", None))
    launch = json.loads((root / "state/launch.json").read_text())
    require(launch["model"] == settings["model"], "ACTIVE_MODEL", settings["model"])
    require(stage <= launch["stage"], "ACTIVE_STAGE", str(launch["stage"]))
    api_check()
    backend_check(root, args.backend)
    token = assistant_check(root) if stage >= 2 else None
    if stage >= 3:
        require(catalog(root)[settings["model"]]["capabilities"]["tools"], "MODEL_SUPPORTS_TOOLS")
        agent_check(root, token)
    if args.voice:
        require(stage >= 4, "VOICE_INSTALLED")
        voice_check(root)
    elif stage >= 4:
        print("VOICE_NOT_RUN: добавьте --voice для проверки синтеза и распознавания.")
    print("CHECKS_OK")
