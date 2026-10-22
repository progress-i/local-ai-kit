"""Install, supervise, inspect and remove the dedicated local AI project."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer

sys.dont_write_bytecode = True
from lib.common import (APP, KIT, LOCK, PLATFORM, atomic_json, bootstrap, canonical_root,
                        digest, download, env_python, execute, http_json, owned_root, project_env, unpack)
from lib.models import (ENGINE_SETTINGS, MODEL_ALIAS, catalog, ensure_model, model_path,
                        save_settings, selected_settings, validate_settings)

MANAGED_TOP = {"project.json", "python", "env", "cache", "tmp", "state", "tools", "src",
               "build", "models", "data", "logs", "browser", "browser-firefox"}


def read_state(root):
    p = root / "state/receipt.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {
        "schema": 1, "stage": 0, "artifacts": {}, "programs": {}, "apt_owned": {}, "apt_borrowed": {}}


def save_state(root, state):
    atomic_json(root / "state/receipt.json", state)


def pip_group(root, group):
    requirement = KIT / f"locks/{group}-{PLATFORM}.txt"
    execute([env_python(root), "-m", "pip", "--isolated", "install", "--require-hashes",
             "--only-binary=:all:", "--no-input", "--disable-pip-version-check",
             "--cache-dir", root / "cache/pip", "-r", requirement], root)
    execute([env_python(root), "-m", "pip", "--isolated", "check"], root)


def artifact(root, state, key, destination=None):
    state["artifacts"][key] = {**LOCK["artifacts"][key], "status": "pending"}
    save_state(root, state)
    p = download(root, key, destination)
    state["artifacts"][key].update(status="verified", path=str(p))
    save_state(root, state)
    return p


def dpkg_packages(include_incomplete=False):
    result = subprocess.run(["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${Status}\n"],
                            capture_output=True, text=True, check=True)
    native = subprocess.run(["dpkg", "--print-architecture"], capture_output=True, text=True, check=True).stdout.strip()
    return {p[0].removesuffix(":" + native): p[1] for line in result.stdout.splitlines()
            if len(p := line.split("\t")) == 3 and
            (p[2] == "install ok installed" or include_incomplete and p[2].split()[-1] != "not-installed")}


def install_compiler(root, state):
    if PLATFORM == "windows":
        target = root / "tools/w64devkit"
        if not (target / "bin/gcc.exe").exists():
            archive = artifact(root, state, "w64devkit", root / "cache/downloads/w64devkit.exe")
            (root / "tools").mkdir(exist_ok=True)
            execute([archive, "-y", "-o" + str(root / "tools")], root)
        for name in ("gcc", "g++", "cmake", "ninja"):
            p = target / "bin" / (name + ".exe")
            if not p.exists():
                raise RuntimeError(f"В w64devkit отсутствует {p.name}.")
        state["programs"]["w64devkit"] = {"version": "2.10.1", "ownership": "private", "path": str(target)}
        save_state(root, state)
        return
    current = dpkg_packages()
    all_current = dpkg_packages(include_incomplete=True)
    required = ["build-essential"]
    baseline_path = root / "state/apt-before.json"
    if not baseline_path.exists():
        atomic_json(baseline_path, all_current)
    baseline = json.loads(baseline_path.read_text())
    missing = [p for p in required if p not in current]
    state["apt_borrowed"].update({p: current[p] for p in required if p in current and p in baseline})
    if missing:
        sudo = [] if os.geteuid() == 0 else ["sudo"]
        # Use private download caches and index lists. No global apt cache cleanup is necessary.
        for rel in ("cache/apt/archives/partial", "cache/apt/lists/partial"):
            (root / rel).mkdir(parents=True, exist_ok=True)
        options = ["-o", f"Dir::Cache::archives={root / 'cache/apt/archives'}",
                   "-o", f"Dir::State::lists={root / 'cache/apt/lists'}", "-o", "APT::Sandbox::User=root"]
        execute([*sudo, "apt-get", *options, "update"], root)
        simulation = execute(["apt-get", *options, "-s", "--no-install-recommends", "install", *required], root, capture=True).stdout
        planned = {}
        for line in simulation.splitlines():
            if not line.startswith("Inst "):
                continue
            match = re.match(r"Inst (\S+)(?: \[([^]]+)\])? \((\S+)", line)
            if not match:
                raise RuntimeError(f"Не удалось разобрать план apt: {line}")
            package, previous, version = match.groups()
            if (previous or package in all_current) and package not in state["apt_owned"]:
                raise RuntimeError(f"Для сборки apt хочет обновить общую программу {package}. Установка остановлена.\n{simulation}")
            if package in state["apt_owned"] and state["apt_owned"][package] != version:
                raise RuntimeError(f"Версия {package} изменилась после первой попытки установки; учёт сохранён.")
            planned[package] = version
        if not planned:
            raise RuntimeError("apt не составил план установки компилятора.")
        # Record ownership BEFORE mutation, including dependencies of a partial install.
        state["apt_owned"].update({k: v for k, v in planned.items() if k not in baseline})
        save_state(root, state)
        atomic_json(root / "state/apt-lock.json", state["apt_owned"])
        execute([*sudo, "apt-get", *options, "install", "-y", "--no-install-recommends", "--no-upgrade", "--no-remove",
                 *[f"{k}={v}" for k, v in planned.items()]], root)
        current = dpkg_packages()
        for name, version in planned.items():
            if current.get(name) != version:
                raise RuntimeError(f"Версия системной зависимости не совпала: {name}.")
    for compiler in ("gcc", "g++", "make"):
        if not shutil.which(compiler):
            raise RuntimeError(f"Компилятор не найден: {compiler}")
        version = execute([compiler, "--version"], root, capture=True).stdout.splitlines()[0]
        state["programs"][compiler] = {"version": version, "ownership": "apt recorded / existing", "path": shutil.which(compiler)}
    save_state(root, state)


def build_environment(root, vulkan=False):
    env = project_env(root)
    if PLATFORM == "windows":
        toolbin = root / "tools/w64devkit/bin"
        env["PATH"] = str(toolbin) + os.pathsep + str(root / "python") + os.pathsep + env.get("PATH", "")
    if vulkan:
        sdk = root / ("tools/vulkan" if PLATFORM == "windows" else "tools/vulkan/x86_64")
        env["VULKAN_SDK"] = str(sdk)
        env["PATH"] = str(sdk / ("Bin" if PLATFORM == "windows" else "bin")) + os.pathsep + env.get("PATH", "")
        if PLATFORM == "linux":
            env["LD_LIBRARY_PATH"] = str(sdk / "lib") + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    return env


def install_sdk(root, state):
    sdk = root / "tools/vulkan"
    marker = sdk / ".local-ai-sdk-complete"
    if marker.exists():
        return
    archive = artifact(root, state, "vulkan-" + PLATFORM,
                       root / "cache/downloads/vulkan-sdk.exe" if PLATFORM == "windows" else None)
    if PLATFORM == "windows":
        if sdk.exists():
            shutil.rmtree(sdk)
        # LunarG's documented file-copy mode avoids registry, PATH and layer registration.
        execute([archive, "--root", sdk, "--accept-licenses", "--default-answer", "--confirm-command",
                 "install", "copy_only=1"], root)
        if not (sdk / "Include/vulkan/vulkan.h").exists() or not (sdk / "Bin/glslc.exe").exists():
            raise RuntimeError("Vulkan SDK не скопирован полностью. Смотрите журнал установщика.")
    else:
        unpack(archive, sdk, strip_top=True)
        if not (sdk / "x86_64/bin/glslc").exists():
            raise RuntimeError("Неожиданная структура Vulkan SDK.")
    marker.write_text("1.4.363.0\n", encoding="ascii")
    state["programs"]["Vulkan SDK"] = {"version": "1.4.363.0", "ownership": "private copy only", "path": str(sdk)}
    save_state(root, state)


def cmake(root):
    return root / ("tools/w64devkit/bin/cmake.exe" if PLATFORM == "windows" else "env/bin/cmake")


def server_binary(root, backend):
    return root / f"build/llama-{backend}/bin" / ("llama-server.exe" if PLATFORM == "windows" else "llama-server")


def ensure_source(root, state, key, target):
    marker = target / ".local-ai-source-sha256"
    expected = LOCK["artifacts"][key]["sha256"]
    if not marker.exists():
        unpack(artifact(root, state, key), target, strip_top=True)
        marker.write_text(expected, encoding="ascii")
    elif marker.read_text() != expected:
        raise RuntimeError(f"Исходники {target} относятся к другой версии.")


def build_llama(root, state, backend):
    target = root / "src/llama.cpp"
    ensure_source(root, state, "llama-source", target)
    ui = target / "tools/ui/dist"
    if not (ui / "index.html").exists():
        unpack(artifact(root, state, "ui"), ui)
    # Assets are verified independently; disable CMake's fallback to an unpinned 'latest'.
    build = root / f"build/llama-{backend}"
    marker = build / ".complete"
    if marker.exists() and server_binary(root, backend).exists():
        return
    vulkan = backend == "vulkan"
    env = build_environment(root, vulkan)
    options = ["-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=OFF", "-DLLAMA_BUILD_TESTS=OFF",
               "-DLLAMA_BUILD_EXAMPLES=OFF", "-DLLAMA_BUILD_APP=OFF", "-DLLAMA_OPENSSL=OFF",
               "-DLLAMA_SUBPROCESS=OFF", "-DLLAMA_BUILD_UI=OFF", "-DLLAMA_USE_PREBUILT_UI=OFF",
               "-DGGML_CUDA=OFF", "-DGGML_VULKAN=" + ("ON" if vulkan else "OFF"),
               "-DLLAMA_BUILD_NUMBER=" + str(LOCK["llama_build_number"]),
               "-DLLAMA_BUILD_COMMIT=" + LOCK["llama_commit"][:7]]
    if PLATFORM == "windows":
        tool = root / "tools/w64devkit/bin"
        options += ["-G", "Ninja", "-DCMAKE_C_COMPILER=" + str(tool / "gcc.exe"),
                    "-DCMAKE_CXX_COMPILER=" + str(tool / "g++.exe"), "-DCMAKE_MAKE_PROGRAM=" + str(tool / "ninja.exe")]
        if vulkan:
            sdk = root / "tools/vulkan"
            options += ["-DVulkan_INCLUDE_DIR=" + str(sdk / "Include"),
                        "-DVulkan_LIBRARY=" + str(sdk / "Lib/vulkan-1.lib"),
                        "-DVulkan_GLSLC_EXECUTABLE=" + str(sdk / "Bin/glslc.exe")]
    execute([cmake(root), "-S", target, "-B", build, *options], root, env=env)
    execute([cmake(root), "--build", build, "--config", "Release", "--parallel", "1", "--target", "llama-server"], root, env=env)
    if not server_binary(root, backend).exists():
        raise RuntimeError("Сборка не создала llama-server.")
    execute([server_binary(root, backend), "--version"], root, capture=True, env=env)
    marker.write_text(LOCK["llama_commit"], encoding="ascii")
    state["programs"]["llama-" + backend] = {"version": LOCK["llama_version"], "commit": LOCK["llama_commit"], "ownership": "built from source"}
    save_state(root, state)


def whisper_binary(root):
    return root / "build/whisper/bin" / ("whisper-cli.exe" if PLATFORM == "windows" else "whisper-cli")


def install_voice(root, state):
    pip_group(root, "voice")
    source = root / "src/whisper.cpp"
    ensure_source(root, state, "whisper-source", source)
    build = root / "build/whisper"
    if not (build / ".complete").exists():
        options = ["-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=OFF", "-DWHISPER_BUILD_TESTS=OFF",
                   "-DWHISPER_CURL=OFF", "-DGGML_CUDA=OFF", "-DGGML_VULKAN=OFF",
                   "-DGGML_NATIVE=OFF", "-DGGML_AVX=ON", "-DGGML_AVX2=ON", "-DGGML_FMA=ON", "-DGGML_F16C=ON"]
        if PLATFORM == "windows":
            tool = root / "tools/w64devkit/bin"
            options += ["-G", "Ninja", "-DCMAKE_C_COMPILER=" + str(tool / "gcc.exe"),
                        "-DCMAKE_CXX_COMPILER=" + str(tool / "g++.exe"), "-DCMAKE_MAKE_PROGRAM=" + str(tool / "ninja.exe")]
        env = build_environment(root)
        execute([cmake(root), "-S", source, "-B", build, *options], root, env=env)
        execute([cmake(root), "--build", build, "--config", "Release", "--parallel", "1", "--target", "whisper-cli"], root, env=env)
        if not whisper_binary(root).exists():
            raise RuntimeError("Не создан whisper-cli.")
        (build / ".complete").write_text(LOCK["whisper_commit"])
    for key, name in (("whisper-model", "ggml-base.bin"), ("piper-model", "ru_RU-denis-medium.onnx"),
                      ("piper-config", "ru_RU-denis-medium.onnx.json"), ("piper-card", "denis-MODEL_CARD.txt")):
        artifact(root, state, key, root / "models" / name)
    state["programs"]["whisper.cpp"] = {"version": LOCK["whisper_version"], "commit": LOCK["whisper_commit"], "ownership": "built from source"}
    save_state(root, state)


def installed_packages(root, state):
    p = execute([env_python(root), "-m", "pip", "--isolated", "list", "--format=json"], root, capture=True)
    state["python_packages"] = json.loads(p.stdout)
    state["python"] = {"version": LOCK["python_version"], "release": LOCK["python_release"], "ownership": "private"}
    save_state(root, state)


def install(root, args):
    if platform.machine().lower() not in ("x86_64", "amd64"):
        raise RuntimeError("Поддерживается только x86-64.")
    if PLATFORM == "linux":
        release = platform.freedesktop_os_release()
        if release.get("ID") != "ubuntu" or release.get("VERSION_ID") not in ("24.04", "26.04"):
            raise RuntimeError("Этот комплект рассчитан на Ubuntu 24.04/26.04 x86-64.")
    state = read_state(root)
    requested = args.stage or 1
    stage = max(requested, state["stage"])
    bootstrap(root)
    for rel in ("state", "logs", "models", "data/workspace", "data/documents"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    # Log the private runtime before installing any Python package.
    state["python"] = {"version": LOCK["python_version"], "ownership": "private"}
    save_state(root, state)
    pip_group(root, "base")
    if state["stage"] and running_owned(root):
        raise RuntimeError("Перед дополнением установки остановите запущенный проект через Ctrl+C.")
    install_compiler(root, state)
    build_llama(root, state, "cpu")
    if args.backend == "vulkan":
        install_sdk(root, state)
        build_llama(root, state, "vulkan")
    settings = selected_settings(root, getattr(args, "model", None))
    module = catalog(root)[settings["model"]]
    path = ensure_model(root, module, allow_download=True)
    state["artifacts"]["model/" + module["id"]] = {**module, "status": "verified", "path": str(path)}
    if stage >= 3:
        pip_group(root, "agent")
    if stage >= 4:
        install_voice(root, state)
    state["stage"] = stage
    installed_packages(root, state)
    save_settings(root, settings)
    print(f"INSTALL_OK stage={stage}; root={root}")


def hardware(root=None):
    print(f"OS: {platform.platform()}; CPU: {platform.processor() or platform.machine()}; logical CPUs: {os.cpu_count()}")
    if PLATFORM == "linux":
        for cmd in (["lscpu"], ["free", "-h"], ["lspci"]):
            if shutil.which(cmd[0]):
                p = subprocess.run(cmd, capture_output=True, text=True)
                if cmd[0] == "lspci":
                    print("\n".join(s for s in p.stdout.splitlines() if re.search(r"VGA|3D|Display", s, re.I)))
                else:
                    print(p.stdout.strip())
        gpu_names = list(Path("/sys/class/drm").glob("card*/device/uevent"))
        for p in gpu_names:
            print(p, p.read_text(errors="replace").strip())
    print("CPU: основной путь; Vulkan: NVIDIA/AMD/Intel с работающим драйвером. NPU не используется.")
    if root and server_binary(root, "vulkan").exists():
        print(execute([server_binary(root, "vulkan"), "--list-devices"], root, capture=True,
                      env=build_environment(root, True)).stdout)


def port_free(port):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            raise RuntimeError(f"Порт {port} занят. Остановите его владельца; проект чужие процессы не завершает.")


def cpu_available_gib():
    import psutil
    return psutil.virtual_memory().available / 1024**3


def running_owned(root):
    """Select by executable path / exact dedicated browser profile, never by name alone."""
    import psutil
    found = []
    # Windows venv's parent python.exe is a redirector waiting for this process.
    own_pids = {os.getpid(), os.getppid()}
    for p in psutil.process_iter(["pid", "exe", "cmdline", "create_time"]):
        try:
            if p.pid in own_pids:
                continue
            exe = Path(p.info["exe"]) if p.info["exe"] else None
            cmd = p.info["cmdline"] or []
            private_exe = exe and (root == exe.parent or root in exe.parents)
            browser = ("--user-data-dir=" + str(root / "browser")) in cmd
            browser |= any(cmd[i] in ("--profile", "-profile") and i + 1 < len(cmd) and cmd[i + 1] == str(root / "browser-firefox") for i in range(len(cmd)))
            if private_exe or browser:
                found.append(p)
        except (psutil.Error, OSError):
            continue
    return found


def stop_processes(processes):
    import psutil
    unique = {p.pid: p for p in processes}
    for p in list(unique.values()):
        try:
            for child in p.children(recursive=True):
                unique[child.pid] = child
        except psutil.Error:
            pass
    for p in reversed(list(unique.values())):
        try:
            p.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(list(unique.values()), timeout=5)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(alive, timeout=3)


def open_project_browser(root, url, env):
    chromium = []
    firefox = []
    if PLATFORM == "windows":
        for prefix in (os.environ.get("PROGRAMFILES(X86)", ""), os.environ.get("PROGRAMFILES", ""), os.environ.get("LOCALAPPDATA", "")):
            if prefix:
                chromium += [Path(prefix) / "Microsoft/Edge/Application/msedge.exe", Path(prefix) / "Google/Chrome/Application/chrome.exe"]
        firefox = [Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Mozilla Firefox/firefox.exe"]
    else:
        chromium = [Path(p) for name in ("google-chrome", "chromium", "chromium-browser") if (p := shutil.which(name))]
        firefox = [Path(p) for name in ("firefox",) if (p := shutil.which(name))]
    for binary in chromium:
        if binary.exists():
            profile = root / "browser"
            profile.mkdir(exist_ok=True)
            return subprocess.Popen([str(binary), "--user-data-dir=" + str(profile), "--no-first-run",
                                     "--no-default-browser-check", url], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for binary in firefox:
        if binary.exists():
            profile = root / "browser-firefox"
            profile.mkdir(exist_ok=True)
            return subprocess.Popen([str(binary), "--no-remote", "--profile", str(profile), url], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Браузер не найден. URL: {url}. Для учёта браузерных данных нужен отдельный профиль внутри {root}.")
    return None


class ModelRuntime:
    """One owned llama-server at a time; settings are committed after a healthy load."""
    def __init__(self, root, backend, device, stage, *, model=None, port=8081):
        self.root, self.backend, self.device, self.stage, self.port = root, backend, device, stage, port
        self.settings = selected_settings(root, model)
        self.process = None
        self.log = None
        self.error = None
        self.closed = threading.Event()
        self.launch_lock = threading.Lock()

    def stop(self):
        with self.launch_lock:
            process = self.process
            self.process = None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if self.log:
            self.log.close()
            self.log = None

    def load(self, *, verify=True):
        module = catalog(self.root)[self.settings["model"]]
        binary = server_binary(self.root, self.backend)
        if not binary.exists():
            raise RuntimeError(f"Сначала выполните install --backend {self.backend}.")
        model = ensure_model(self.root, module, allow_download=False) if verify else model_path(self.root, module)
        available = cpu_available_gib()
        print(f"Модель: {module['name']}; доступно RAM: {available:.1f} GiB", flush=True)
        if available < module["min_free_gib"]:
            raise RuntimeError(f"Для профиля требуется хотя бы {module['min_free_gib']} GiB свободной RAM.")
        env = build_environment(self.root, self.backend == "vulkan")
        values = self.settings
        env["OMP_NUM_THREADS"] = str(values["threads"])
        argv = [str(binary), "--model", str(model), "--alias", MODEL_ALIAS,
                "--host", "127.0.0.1", "--port", str(self.port), "--parallel", "1", "--jinja",
                "--ctx-size", str(values["context"]), "--threads", str(values["threads"]),
                "--batch-size", str(values["batch"]), "--ubatch-size", str(values["ubatch"]),
                "--cache-ram", str(values["cache_ram"]), "--ctx-checkpoints", str(values["ctx_checkpoints"]),
                "--reasoning", "on" if values["reasoning"] else "off"]
        if values["reasoning"]:
            argv += ["--reasoning-budget", str(values["reasoning_budget"])]
        if self.backend == "cpu":
            argv += ["--device", "none", "--gpu-layers", "0"]
        else:
            devices = execute([binary, "--list-devices"], self.root, capture=True, env=env)
            listing = devices.stdout + devices.stderr
            print(listing)
            match = next((line for line in listing.splitlines() if re.match(r"\s*" + re.escape(self.device) + r":", line)), "")
            if not match or re.search(r"llvmpipe|lavapipe|software|swiftshader", match, re.I):
                raise RuntimeError("Реальный Vulkan GPU не найден. Выполните start --backend cpu или проверьте драйвер.")
            argv += ["--device", self.device, "--gpu-layers", "auto"]
        (self.root / "logs").mkdir(exist_ok=True)
        log_path = self.root / "logs/llama-server.log"
        with self.launch_lock:
            if self.closed.is_set():
                raise RuntimeError("Проект останавливается.")
            self.log = log_path.open("w", encoding="utf-8")
            self.process = subprocess.Popen(argv, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        import psutil
        launch = {"backend": self.backend, "device": self.device, "stage": self.stage,
                  "model": module["id"], "settings": values, "pid": self.process.pid,
                  "create_time": psutil.Process(self.process.pid).create_time(), "argv": argv, "time": time.time()}
        atomic_json(self.root / "state/launch.json", launch)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if self.closed.is_set():
                raise RuntimeError("Проект останавливается.")
            if self.process.poll() is not None:
                raise RuntimeError("llama-server завершился:\n" + log_path.read_text(errors="replace")[-5000:])
            try:
                if http_json(self.port, "/health", timeout=1).get("status") == "ok":
                    models = http_json(self.port, "/v1/models", timeout=2)["data"]
                    if not any(m["id"] == MODEL_ALIAS for m in models):
                        raise RuntimeError("Сервер вернул неверный псевдоним модели.")
                    break
            except (OSError, TimeoutError):
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError(f"Модель не загрузилась за 300 секунд. Журнал: {log_path}")
        self.error = None
        state = read_state(self.root)
        state["artifacts"]["model/" + module["id"]] = {**module, "status": "verified", "path": str(model)}
        save_state(self.root, state)

    def apply(self, candidate):
        if self.closed.is_set():
            raise RuntimeError("Проект останавливается.")
        if not isinstance(candidate, dict) or not isinstance(candidate.get("model"), str):
            raise ValueError("Выберите модель.")
        modules = catalog(self.root)
        if candidate["model"] not in modules:
            raise ValueError("Модуль модели не найден.")
        module = modules[candidate["model"]]
        validate_settings(module, {k: v for k, v in candidate.items() if k != "model"})
        previous = dict(self.settings)
        reload_needed = any(candidate[k] != previous[k] for k in ENGINE_SETTINGS)
        reload_needed |= self.process is None or self.process.poll() is not None
        if not reload_needed:
            save_settings(self.root, candidate)
            self.settings = dict(candidate)
            return False
        # Download and verify before unloading the working model. Never overwrite an existing GGUF.
        ensure_model(self.root, module, allow_download=True)
        self.stop()
        self.settings = dict(candidate)
        try:
            self.load(verify=False)
            save_settings(self.root, candidate)
        except Exception as failure:
            self.stop()
            self.settings = previous
            if self.closed.is_set():
                raise
            try:
                self.load(verify=False)
            except Exception as rollback:
                self.stop()
                self.error = str(rollback)
                raise RuntimeError(f"Новые настройки не применены: {failure}\nПредыдущая модель тоже не загрузилась: {rollback}") from failure
            raise RuntimeError(f"Новые настройки не применены; предыдущая модель восстановлена.\n{failure}") from failure
        return True


def start(root, args):
    state = read_state(root)
    stage = args.stage or state["stage"]
    if not 1 <= stage <= state["stage"]:
        raise RuntimeError("Сначала установите выбранный этап.")
    if running_owned(root):
        raise RuntimeError("Уже запущен процесс из этой папки. Завершите предыдущий запуск через Ctrl+C.")
    port_free(8081)
    port_free(8080)
    runtime = ModelRuntime(root, args.backend, args.device, stage, model=getattr(args, "model", None))
    server = None
    thread = None
    browsers = []
    try:
        runtime.load()
        save_settings(root, runtime.settings)
        from assistant import Assistant, handler_for
        app = Assistant(root, stage, runtime=runtime)
        server = ThreadingHTTPServer(("127.0.0.1", 8080), handler_for(app))
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = "http://127.0.0.1:8080"
        print(f"READY stage={stage} backend={args.backend}: {url}\nЖурнал: {root / 'logs/llama-server.log'}\nCtrl+C — остановить проект.", flush=True)
        if not args.no_browser:
            browser = open_project_browser(root, url, build_environment(root, args.backend == "vulkan"))
            if browser:
                browsers.append(browser)
        while thread.is_alive():
            # The UI stays available after a failed model load; Apply can restore it.
            time.sleep(0.5)
        raise RuntimeError("Интерфейс завершился.")
    except KeyboardInterrupt:
        print("Остановка...")
    finally:
        runtime.closed.set()
        runtime.stop()
        if server:
            server.shutdown()
            server.server_close()
        if thread:
            thread.join(timeout=3)
        import psutil
        candidates = running_owned(root)
        for proc in browsers:
            if proc.poll() is None:
                try:
                    candidates.append(psutil.Process(proc.pid))
                except psutil.Error:
                    pass
        stop_processes(candidates)


def inventory(root):
    state = read_state(root)
    print(f"Выделенная папка: {root}")
    for p in sorted(root.iterdir()):
        print(f"  {p.name}{'/' if p.is_dir() else ''}")
    print("Зависимости и владение:")
    print(json.dumps(state, ensure_ascii=False, indent=2))
    # A complete per-file list remains available for review without flooding the terminal.
    entries = []
    for current, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            entries.append(str((Path(current) / name).relative_to(root)))
    output = root / "state/file-inventory.txt"
    output.parent.mkdir(exist_ok=True)
    output.write_text("\n".join(entries) + "\n", encoding="utf-8")
    print(f"Все пути ({len(entries)}): {output}")


def remove(root):
    if PLATFORM == "windows":
        raise RuntimeError("Для удаления Windows используйте local-ai.ps1 remove.")
    state = read_state(root)
    unknown = sorted(p.name for p in root.iterdir() if p.name not in MANAGED_TOP and not p.name.endswith(".extracting"))
    if unknown:
        raise RuntimeError("Обнаружены неучтённые файлы в корне. Сначала перенесите их: " + ", ".join(unknown))
    current = dpkg_packages(include_incomplete=True)
    packages = {p: v for p, v in state["apt_owned"].items() if p in current}
    for p, v in packages.items():
        if current[p] != v:
            raise RuntimeError(f"Общая зависимость {p} уже изменена вне проекта ({v} -> {current[p]}). Автоматическое удаление остановлено; учёт сохранён.")
    if packages:
        plan = execute(["apt-get", "-s", "purge", *packages], root, capture=True).stdout
        removed = set(re.findall(r"^(?:Remv|Purg) (\S+)", plan, re.M))
        if removed - set(packages):
            raise RuntimeError("apt хочет удалить чужие программы; удаление остановлено.\n" + plan)
        print(plan)
    inventory(root)
    print("Будут завершены только процессы с исполняемыми файлами внутри корня проекта и его отдельный браузерный профиль.")
    if input("Введите DELETE для удаления перечисленного: ") != "DELETE":
        print("Удаление отменено.")
        return
    # Use psutil from our env if available. A broken bootstrap can still be removed safely after checking /proc.
    try:
        import psutil
    except ImportError:
        py = env_python(root)
        if py.exists() and Path(sys.executable).resolve() != py.resolve():
            # Confirmation is not requested a second time; a private one-shot ticket binds it to this root.
            ticket = root / "state/delete-approved.json"
            atomic_json(ticket, {"root": str(root), "expires": time.time() + 60})
            result = subprocess.run([str(py), "-B", str(APP / "manage.py"), "--root", str(root), "remove-approved"])
            if result.returncode:
                raise RuntimeError("Удаление не завершено; папка и учёт сохранены.")
            return
        if not Path("/proc").exists():
            raise RuntimeError("Не удалось проверить процессы. Удаление остановлено.")
        for proc in Path("/proc").iterdir():
            if proc.name.isdigit():
                try:
                    exe = (proc / "exe").resolve(strict=True)
                    command = (proc / "cmdline").read_bytes()
                    if root in exe.parents or str(root / "browser").encode() in command:
                        raise RuntimeError("Процесс проекта ещё работает. Остановите его и повторите удаление.")
                except (FileNotFoundError, PermissionError):
                    continue
        finish_remove(root, state, packages)
    else:
        stop_processes(running_owned(root))
        finish_remove(root, state, packages)


def finish_remove(root, state, packages):
    if packages:
        current = dpkg_packages(include_incomplete=True)
        if any(current.get(p) != v for p, v in packages.items()):
            raise RuntimeError("Состав зависимостей изменился во время подтверждения. Повторите удаление.")
        plan = execute(["apt-get", "-s", "purge", *packages], root, capture=True).stdout
        order = list(dict.fromkeys(re.findall(r"^(?:Remv|Purg) (\S+)", plan, re.M)))
        if set(order) - set(packages):
            raise RuntimeError("Новый план затрагивает чужие программы. Удаление остановлено.")
        sudo = [] if os.geteuid() == 0 else ["sudo"]
        # dpkg only processes this exact list and refuses unmet reverse dependencies.
        # Unlike an apt resolver it cannot silently add a newly dependent foreign package.
        execute([*sudo, "dpkg", "--purge", *order, *[p for p in packages if p not in order]], root)
    # rmtree does not traverse symlinks; Python 3.12 also does not descend Windows junctions.
    os.chdir(root.parent)
    shutil.rmtree(root)
    if root.exists():
        raise RuntimeError("Папка удалена не полностью.")
    print("REMOVE_OK: все учтённые ресурсы проекта удалены.")


def main():
    parser = argparse.ArgumentParser(description="Локальный ИИ: установка, запуск, проверки, удаление.")
    parser.add_argument("--root", default=str(Path.home() / "LocalAISeries"))
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("install", "start", "check"):
        p = sub.add_parser(name)
        p.add_argument("--stage", type=int, choices=range(0, 5), default=0)
        p.add_argument("--backend", choices=("cpu", "vulkan"), default="cpu")
        p.add_argument("--model", help="ID подключённого модуля модели")
        if name == "start":
            p.add_argument("--device", default="Vulkan0")
            p.add_argument("--no-browser", action="store_true")
        if name == "check":
            p.add_argument("--offline", action="store_true")
            p.add_argument("--voice", action="store_true")
    for name in ("hardware", "inventory", "remove", "remove-approved"):
        sub.add_parser(name)
    args = parser.parse_args()
    if args.action == "hardware":
        candidate = canonical_root(args.root)
        hardware(owned_root(candidate) if (candidate / "project.json").exists() else None)
        return
    root = owned_root(args.root, create=args.action == "install")
    if args.action == "install":
        install(root, args)
    elif args.action == "start":
        start(root, args)
    elif args.action == "inventory":
        inventory(root)
    elif args.action == "check":
        from checks import run_checks
        run_checks(root, args)
    elif args.action == "remove":
        remove(root)
    else:
        ticket = root / "state/delete-approved.json"
        approved = json.loads(ticket.read_text())
        ticket.unlink()
        if approved["root"] != str(root) or approved["expires"] < time.time():
            raise RuntimeError("Подтверждение удаления истекло.")
        state = read_state(root)
        # Parent already checked package removal; check again before the final operation.
        current = dpkg_packages(include_incomplete=True)
        packages = {p: v for p, v in state["apt_owned"].items() if p in current}
        if any(current[p] != v for p, v in packages.items()):
            raise RuntimeError("Состав общих зависимостей изменился во время удаления.")
        if packages:
            plan = execute(["apt-get", "-s", "purge", *packages], root, capture=True).stdout
            if set(re.findall(r"^(?:Remv|Purg) (\S+)", plan, re.M)) - set(packages):
                raise RuntimeError("План удаления затрагивает чужие программы.")
        stop_processes(running_owned(root))
        finish_remove(root, state, packages)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Операция прервана. Повторный запуск продолжит установку.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        sys.exit(1)
