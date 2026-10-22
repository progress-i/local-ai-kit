"""Actual WASI boundary, approval, persistence, HTTP and deletion safeguards.

The LLM is stubbed here. These tests do not count as a Qwen or microphone test.
"""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import subprocess
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import urllib.error
import urllib.request
import sys
from argparse import Namespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from assistant import Assistant, handler_for
from lib.common import KIT, atomic_json, bootstrap, env_python, owned_root
from lib.sandbox import Sandbox, security_check
import manage


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=KIT.parent, prefix="local-ai-test-")
        self.base = Path(self.temp.name)
        self.root = owned_root(self.base / "LocalAISeries", create=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_real_wasi_boundary(self):
        result = security_check(self.root / "workspace")
        self.assertEqual(result["raw_traversal"], "PASS")
        self.assertEqual(result["no_overwrite"], "PASS")
        self.assertEqual(result["network_imports"], "none")

    def test_workspace_symlink_is_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        alias = self.root / "workspace"
        try:
            alias.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("OS does not permit symlinks")
        with self.assertRaises(ValueError):
            Sandbox(alias)

    def test_unknown_tool_and_command_text(self):
        sandbox = Sandbox(self.root / "workspace")
        with self.assertRaises(ValueError):
            sandbox.call("shell", {"command": "whoami"})
        with self.assertRaises(ValueError):
            sandbox.call("read_note", {"name": "../secret.txt"})
        literal = "$(touch escaped); echo hello & whoami"
        sandbox.call("write_note", {"name": "literal.txt", "text": literal})
        self.assertEqual(sandbox.call("read_note", {"name": "literal.txt"})["text"], literal)
        self.assertFalse((self.root / "escaped").exists())

    def test_approval_then_real_wasi_write_and_disk_history(self):
        app = Assistant(self.root, 3)
        chat = app.new_chat()
        call = {"id": "call_1", "type": "function", "function": {"name": "write_note", "arguments": json.dumps({"name": "test.txt", "text": "Привет"})}}
        with patch.object(app, "completion", side_effect=[{"role": "assistant", "content": None, "tool_calls": [call]}, {"role": "assistant", "content": "Готово"}]):
            reply = app.ask(chat["id"], "Создай test.txt", True)
            self.assertIsNotNone(reply["pending"])
            self.assertFalse((self.root / "data/workspace/test.txt").exists())
            reply = app.approve(chat["id"], True)
        self.assertEqual((self.root / "data/workspace/test.txt").read_text(), "Привет")
        restarted = Assistant(self.root, 3)
        self.assertEqual(restarted.load(chat["id"]), reply)
        self.assertTrue(reply["events"][0]["result"]["ok"])
        with self.assertRaises(ValueError):
            app.approve(chat["id"], True)

    def test_denied_write_does_not_create_file(self):
        app = Assistant(self.root, 3)
        chat = app.new_chat()
        call = {"id": "call_1", "type": "function", "function": {"name": "write_note", "arguments": json.dumps({"name": "denied.txt", "text": "no"})}}
        with patch.object(app, "completion", side_effect=[{"role": "assistant", "content": None, "tool_calls": [call]}, {"role": "assistant", "content": "Отклонено"}]):
            app.ask(chat["id"], "create", True)
            reply = app.approve(chat["id"], False)
        self.assertFalse((self.root / "data/workspace/denied.txt").exists())
        self.assertFalse(reply["events"][0]["result"]["ok"])

    def test_invalid_tool_after_approved_write_keeps_chat_usable(self):
        app = Assistant(self.root, 3)
        chat = app.new_chat()
        outside = self.root / "data/outside.txt"
        outside.write_text("KEEP", encoding="utf-8")
        good = {"id": "good", "type": "function", "function": {"name": "write_note", "arguments": json.dumps({"name": "good.txt", "text": "Привет"})}}
        bad = {"id": "bad", "type": "function", "function": {"name": "write_note", "arguments": json.dumps({"name": "../outside.txt", "text": "ATTACK"})}}
        with patch.object(app, "completion", side_effect=[
            {"role": "assistant", "content": None, "tool_calls": [good]},
            {"role": "assistant", "content": None, "tool_calls": [bad]},
            {"role": "assistant", "content": "Недопустимый путь."},
            {"role": "assistant", "content": "Диалог продолжается."},
        ]):
            app.ask(chat["id"], "Создай файл", True)
            reply = app.approve(chat["id"], True)
            self.assertIsNone(reply["pending"])
            self.assertFalse(reply["events"][-1]["result"]["ok"])
            results = {m["tool_call_id"] for m in reply["messages"] if m["role"] == "tool"}
            self.assertEqual(results, {"good", "bad"})
            self.assertEqual(app.load(chat["id"]), reply)
            reply = app.ask(chat["id"], "Продолжим", True)
        self.assertEqual(reply["messages"][-1]["content"], "Диалог продолжается.")
        self.assertEqual(outside.read_text(encoding="utf-8"), "KEEP")
        self.assertEqual((self.root / "data/workspace/good.txt").read_text(encoding="utf-8"), "Привет")

    def test_invalid_batch_never_approves_other_writes(self):
        app = Assistant(self.root, 3)
        chat = app.new_chat()
        calls = [
            {"id": "safe", "type": "function", "function": {"name": "write_note", "arguments": json.dumps({"name": "safe.txt", "text": "hello"})}},
            {"id": "bad", "type": "function", "function": {"name": "write_note", "arguments": "{"}},
        ]
        with patch.object(app, "completion", side_effect=[
            {"role": "assistant", "content": None, "tool_calls": calls},
            {"role": "assistant", "content": "Вызовы отклонены."},
        ]):
            reply = app.ask(chat["id"], "Создай файлы", True)
        self.assertIsNone(reply["pending"])
        self.assertFalse((self.root / "data/workspace/safe.txt").exists())
        self.assertEqual(len(reply["events"]), 2)
        self.assertTrue(all(not event["result"]["ok"] for event in reply["events"]))

    def test_malformed_followup_preserves_completed_write(self):
        app = Assistant(self.root, 3)
        chat = app.new_chat()
        call = {"id": "good", "type": "function", "function": {"name": "write_note", "arguments": json.dumps({"name": "note.txt", "text": "Привет"})}}
        with patch.object(app, "completion", side_effect=[
            {"role": "assistant", "content": None, "tool_calls": [call]},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "bad", "function": None}]},
        ]):
            app.ask(chat["id"], "Создай заметку", True)
            with self.assertRaisesRegex(ValueError, "некорректный вызов"):
                app.approve(chat["id"], True)
        saved = app.load(chat["id"])
        self.assertIsNone(saved["pending"])
        self.assertEqual(saved["messages"][-1]["role"], "tool")
        self.assertEqual(saved["messages"][-1]["tool_call_id"], "good")
        self.assertEqual((self.root / "data/workspace/note.txt").read_text(encoding="utf-8"), "Привет")
        with patch.object(app, "completion", return_value={"role": "assistant", "content": "Продолжаем."}):
            reply = app.ask(chat["id"], "Продолжим", True)
        self.assertEqual(reply["messages"][-1]["content"], "Продолжаем.")

    @unittest.skipIf(os.name == "nt", "Linux bootstrap recovery test")
    def test_bootstrap_repairs_incomplete_venv_and_preserves_data(self):
        (self.root / "python").symlink_to(Path(sys.base_prefix), target_is_directory=True)
        binary = self.root / "python/bin/python3"
        subprocess.run([str(binary), "-B", "-m", "venv", "--without-pip", str(self.root / "env")], check=True)
        data = self.root / "data"
        data.mkdir()
        keep = data / "keep.txt"
        keep.write_text("KEEP", encoding="utf-8")
        probe = subprocess.run([str(env_python(self.root)), "-I", "-m", "pip", "--version"], capture_output=True)
        self.assertNotEqual(probe.returncode, 0)
        py = bootstrap(self.root)
        probe = subprocess.run([str(py), "-I", "-m", "pip", "--version"], capture_output=True)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(keep.read_text(encoding="utf-8"), "KEEP")
        with patch("lib.common.execute") as execute:
            self.assertEqual(bootstrap(self.root), py)
            execute.assert_not_called()

    @unittest.skipIf(os.name == "nt", "Linux symlink guard test")
    def test_bootstrap_does_not_clear_a_foreign_env_link(self):
        (self.root / "python").symlink_to(Path(sys.base_prefix), target_is_directory=True)
        outside = self.base / "foreign-env"
        outside.mkdir()
        keep = outside / "keep.txt"
        keep.write_text("KEEP", encoding="utf-8")
        (self.root / "env").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "ссылкой/junction"):
            bootstrap(self.root)
        self.assertEqual(keep.read_text(encoding="utf-8"), "KEEP")

    def test_resume_install_restores_dependencies_before_process_check(self):
        state = manage.read_state(self.root)
        state["stage"] = 2
        manage.save_state(self.root, state)
        available = set()

        def packages(root, group):
            available.add(group)

        def processes(root):
            if "base" not in available:
                raise ModuleNotFoundError("No module named 'psutil'")
            return []

        with (patch.object(manage.platform, "machine", return_value="x86_64"),
              patch.object(manage.platform, "freedesktop_os_release", return_value={"ID": "ubuntu", "VERSION_ID": "24.04"}, create=True),
              patch.object(manage, "bootstrap"),
              patch.object(manage, "pip_group", side_effect=packages),
              patch.object(manage, "running_owned", side_effect=processes),
              patch.object(manage, "install_compiler"),
              patch.object(manage, "build_llama"),
              patch.object(manage, "artifact"),
              patch.object(manage, "ensure_model", return_value=self.root / "models/model.gguf"),
              patch.object(manage, "installed_packages")):
            manage.install(self.root, Namespace(stage=1, backend="cpu"))
        self.assertEqual(manage.read_state(self.root)["stage"], 2)

    def test_http_rejects_cross_origin_and_missing_token(self):
        app = Assistant(self.root, 2)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(app))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        url = f"http://127.0.0.1:{server.server_port}/api/new"
        try:
            for headers in ({"Host": "127.0.0.1:8080"}, {"Host": "127.0.0.1:8080", "X-Local-Token": app.token, "Origin": "https://example.invalid"}, {"Host": "example.invalid", "X-Local-Token": app.token}):
                req = urllib.request.Request(url, data=b"{}", headers=headers)
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    opener.open(req)
                self.assertEqual(ctx.exception.code, 400)
            req = urllib.request.Request(url, data=b"{}", headers={"Host": "127.0.0.1:8080", "X-Local-Token": app.token})
            result = json.load(opener.open(req))
            self.assertEqual(app.load(result["id"])["id"], result["id"])
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_existing_folder_and_system_root_are_rejected(self):
        foreign = self.base / "foreign"
        foreign.mkdir()
        secret = foreign / "keep.txt"
        secret.write_text("keep")
        with self.assertRaises(RuntimeError):
            owned_root(foreign, create=True)
        with self.assertRaises(RuntimeError):
            owned_root(Path.home(), create=True)
        self.assertEqual(secret.read_text(), "keep")

    def test_remove_cancel_and_foreign_dependency_guard(self):
        data = self.root / "data"
        data.mkdir()
        keep = data / "keep.txt"
        keep.write_text("keep")
        with patch.object(manage, "dpkg_packages", return_value={}), patch("builtins.input", return_value="NO"):
            manage.remove(self.root)
        self.assertEqual(keep.read_text(), "keep")

        state = manage.read_state(self.root)
        state["apt_owned"] = {"project-dep": "1"}
        manage.save_state(self.root, state)
        class Result:
            stdout = "Remv project-dep [1]\nRemv unrelated-program [2]\n"
        with patch.object(manage, "dpkg_packages", return_value={"project-dep": "1"}), patch.object(manage, "execute", return_value=Result()):
            with self.assertRaisesRegex(RuntimeError, "чужие программы"):
                manage.remove(self.root)
        self.assertEqual(keep.read_text(), "keep")

    def test_file_removal_preserves_outside_symlink_target(self):
        outside = self.base / "outside.txt"
        outside.write_text("KEEP_OUTSIDE")
        data = self.root / "data"
        data.mkdir()
        (data / "owned.txt").write_text("owned")
        try:
            (data / "link.txt").symlink_to(outside)
        except OSError:
            pass
        old_cwd = Path.cwd()
        try:
            manage.finish_remove(self.root, manage.read_state(self.root), {})
        finally:
            os.chdir(old_cwd)
        self.assertFalse(self.root.exists())
        self.assertEqual(outside.read_text(), "KEEP_OUTSIDE")



if __name__ == "__main__":
    unittest.main()
