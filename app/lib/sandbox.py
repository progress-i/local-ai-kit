"""Real WASI filesystem isolation. Tool arguments are data, never executable code."""
from __future__ import annotations

import json
from pathlib import Path
import re
import struct


TOOLS = [
    {"type": "function", "function": {"name": "write_note", "description": "Создать новый текстовый файл в изолированной папке. Запись подтверждает пользователь. Существующие файлы не перезаписываются.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "Имя .txt или .md без папок, например test.txt"}, "text": {"type": "string"}}, "required": ["name", "text"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "read_note", "description": "Прочитать небольшой .txt или .md из изолированной папки.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"], "additionalProperties": False}}},
]


class Sandbox:
    def __init__(self, workspace: Path):
        import wasmtime as wt
        self.wt = wt
        workspace = workspace.absolute()
        if workspace.is_symlink() or workspace.resolve() != workspace:
            raise ValueError("Папка инструментов и её родители не могут быть ссылками/junction.")
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        config = wt.Config()
        config.consume_fuel = True
        config.wasm_threads = False
        self.engine = wt.Engine(config)
        self.module = wt.Module.from_file(self.engine, str(Path(__file__).with_name("file_tools.wat")))
        expected = {"path_open", "fd_read", "fd_write", "fd_close"}
        if {i.name for i in self.module.imports} != expected:
            raise RuntimeError("Неожиданные возможности WASI-модуля.")

    @staticmethod
    def validate(tool, args):
        if tool not in ("read_note", "write_note") or not isinstance(args, dict):
            raise ValueError("Инструмент не разрешён.")
        keys = {"name", "text"} if tool == "write_note" else {"name"}
        if set(args) != keys:
            raise ValueError("Неверный набор аргументов.")
        name = args.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.(txt|md)", name):
            raise ValueError("Допускается только простое имя .txt/.md без пути.")
        if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
            raise ValueError("Зарезервированное имя Windows.")
        if tool == "write_note":
            if not isinstance(args["text"], str) or len(args["text"].encode("utf-8")) > 8192:
                raise ValueError("Максимум 8192 байта UTF-8.")

    def raw(self, mode: int, path: str, content=b""):
        """Used by security checks too: bypasses lexical validation to test WASI itself."""
        wt = self.wt
        path_bytes = path.encode("utf-8")
        if len(path_bytes) > 512 or len(content) > 8192:
            raise ValueError("Слишком длинные данные.")
        with wt.Store(self.engine) as store:
            store.set_limits(memory_size=65536, instances=1, memories=1, tables=0)
            store.set_fuel(100_000)
            wasi = wt.WasiConfig()
            # No inherit_env, inherit_stdio or socket inheritance.
            wasi.preopen_dir(str(self.workspace), "/work")
            store.set_wasi(wasi)
            with wt.Linker(self.engine) as linker:
                linker.define_wasi()
                instance = linker.instantiate(store, self.module)
                exports = instance.exports(store)
                memory = exports["memory"]
                memory.write(store, path_bytes, 1024)
                memory.write(store, content, 4096)
                code = exports["run"](store, mode, len(path_bytes), len(content) if mode else 8193)
                count = struct.unpack("<I", memory.read(store, 16, 20))[0]
                result = bytes(memory.read(store, 16384, 16384 + count)) if not mode and not code else b""
                return code, count, result

    def call(self, tool, args):
        self.validate(tool, args)
        writing = tool == "write_note"
        if writing:
            entries = list(self.workspace.iterdir())
            if len(entries) >= 32 or sum(p.lstat().st_size for p in entries if not p.is_symlink()) > 256 * 1024:
                raise ValueError("Папка инструментов достигла лимита: 32 файла / 256 KiB.")
        data = args.get("text", "").encode("utf-8")
        code, count, result = self.raw(int(writing), args["name"], data)
        if code:
            raise ValueError(f"WASI отказал в операции (errno={code}). Файл может уже существовать или выходить за границу папки.")
        if writing and count != len(data):
            raise ValueError("WASI записал неполный файл.")
        if not writing and count > 8192:
            raise ValueError("Файл превышает 8192 байта.")
        return {"ok": True, "name": args["name"], **({"written_bytes": count} if writing else {"text": result.decode("utf-8")})}


def security_check(workspace):
    """Tests the runtime boundary with traversal and symlink attacks, not just our regex."""
    import tempfile
    with tempfile.TemporaryDirectory(dir=workspace.parent, prefix="sandbox-test-") as directory:
        base = Path(directory)
        secret = base / "outside.txt"
        secret.write_text("HOST_SECRET", encoding="utf-8")
        box = Sandbox(base / "work")
        assert box.call("write_note", {"name": "test.txt", "text": "Привет"})["ok"]
        assert box.call("read_note", {"name": "test.txt"})["text"] == "Привет"
        assert box.raw(1, "test.txt", b"overwrite")[0] != 0
        for name in ("../outside.txt", str(secret), "../../outside.txt"):
            assert box.raw(0, name)[0] != 0, name
            assert box.raw(1, name, b"ATTACK")[0] != 0, name
        assert secret.read_text() == "HOST_SECRET"
        symlink = base / "work/escape.txt"
        symlink_status = "tested"
        try:
            symlink.symlink_to(secret)
        except OSError:
            symlink_status = "SKIP: ОС не разрешила создание symlink"
        else:
            assert box.raw(0, "escape.txt")[0] != 0
            assert box.raw(1, "escape.txt", b"ATTACK")[0] != 0
        # No network capability is imported, no inherited descriptors or host callbacks exist.
        assert all(i.module == "wasi_snapshot_preview1" for i in box.module.imports)
        return {"write_read": "PASS", "no_overwrite": "PASS", "raw_traversal": "PASS",
                "raw_symlink": symlink_status, "network_imports": "none", "memory_limit": 65536, "fuel": 100000}
