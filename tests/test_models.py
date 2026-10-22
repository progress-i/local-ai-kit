"""Modules, existing data, context budgeting and real HTTP/process reloads.

The subprocess fixture is a tiny HTTP server, not an LLM. RAM and psutil's
creation-time probe are mocked because this test environment has no /proc.
"""
import copy
import hashlib
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from assistant import Assistant, handler_for
from lib.common import KIT, LOCK, atomic_json, owned_root
from lib.models import (MODEL_ALIAS, add_module, catalog, ensure_model, model_path,
                        preferences, save_settings, selected_settings, validate_module,
                        validate_settings)
from manage import ModelRuntime
import checks


FIXTURE_SERVER = r'''
import argparse, json, os, signal, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--port', type=int)
p.add_argument('--model')
p.add_argument('--ctx-size', type=int)
a, _ = p.parse_known_args()
events = Path(a.model).parent / 'fixture-events.jsonl'
with events.open('a') as f:
    f.write(json.dumps({'pid': os.getpid(), 'model': a.model, 'context': a.ctx_size})+'\n')
if a.ctx_size == 8192:
    print('fixture: simulated load failure', flush=True)
    sys.exit(17)
class Handler(BaseHTTPRequestHandler):
    def send(self, data):
        data = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        self.send({'data':[{'id':'local-ai'}]} if self.path == '/v1/models' else {'status':'ok'})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/apply-template': self.send({'prompt':json.dumps(body,ensure_ascii=False)})
        elif self.path == '/tokenize': self.send({'tokens':[1]*(len(body['content'])//4)})
        else: self.send({'choices':[{'message':{'role':'assistant','content':'Ответ тестового HTTP-сервера.'}}]})
    def log_message(self, *args): pass
server = ThreadingHTTPServer(('127.0.0.1',a.port), Handler)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
try: server.serve_forever(poll_interval=0.05)
finally: server.server_close()
'''


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=KIT.parent, prefix="model-test-")
        self.base = Path(self.temp.name)
        self.root = owned_root(self.base / "LocalAISeries", create=True)
        self.original = copy.deepcopy(LOCK["models"]["modules"][LOCK["models"]["default"]])

    def tearDown(self):
        self.temp.cleanup()

    def module(self, ident="test-model", *, tools=False):
        data = ("test fixture " + ident).encode()
        module = {**copy.deepcopy(self.original), "id": ident, "name": ident, "file": ident + ".gguf",
                  "url": "https://example.invalid/" + ident + ".gguf", "size": len(data),
                  "sha256": hashlib.sha256(data).hexdigest(), "min_free_gib": 0.1,
                  "capabilities": {"tools": tools, "reasoning": False}}
        add_module(self.root, module)
        (self.root / "models").mkdir(exist_ok=True)
        model_path(self.root, module).write_bytes(data)
        return module

    def test_existing_install_defaults_and_no_redownload(self):
        atomic_json(self.root / "state/receipt.json", {"schema": 1, "stage": 4, "artifacts": {},
                    "programs": {}, "apt_owned": {}, "apt_borrowed": {}})
        self.assertEqual(selected_settings(self.root)["context"], 4096)
        self.assertEqual(selected_settings(self.root)["model"], self.original["id"])
        module = self.module()
        before = model_path(self.root, module).stat().st_mtime_ns
        with patch("urllib.request.urlopen") as network:
            ensure_model(self.root, module, allow_download=True)
            network.assert_not_called()
        self.assertEqual(model_path(self.root, module).stat().st_mtime_ns, before)
        self.assertEqual(json.loads((self.root / "state/receipt.json").read_text())["stage"], 4)

    def test_settings_are_saved_per_model_and_keep_existing_data(self):
        app = Assistant(self.root, 2)
        legacy = app.new_chat()
        legacy.pop("model")
        app.save(legacy)
        app.save_memory("Мой город Томск")
        app.add_document("note.txt", "KEEP")
        module = self.module()
        values = {"model": module["id"], **module["defaults"], "temperature": 0.65}
        save_settings(self.root, values)
        self.assertEqual(selected_settings(self.root), values)
        self.assertEqual(app.load(legacy["id"])["model"], self.original["id"])
        self.assertEqual(app.new_chat()["model"], module["id"])
        with self.assertRaisesRegex(ValueError, "другой моделью"):
            app.ask(legacy["id"], "Продолжим")
        save_settings(self.root, {"model": self.original["id"], **self.original["defaults"]})
        self.assertEqual(selected_settings(self.root, module["id"])["temperature"], 0.65)
        self.assertEqual((self.root / "data/documents/note.txt").read_text(), "KEEP")
        self.assertEqual((self.root / "data/memory.txt").read_text(), "Мой город Томск")

    def test_module_validation_rejects_paths_scripts_and_id_collisions(self):
        for overrides in ({"file": "../other.gguf"}, {"id": "../bad"}, {"url": "file:///tmp/model.gguf"},
                          {"url": "https://user:secret@example.invalid/model"}, {"command": "echo unsafe"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                validate_module({**copy.deepcopy(self.original), **overrides})
        module = self.module()
        with self.assertRaises(ValueError):
            add_module(self.root, module)
        with self.assertRaises(ValueError):
            add_module(self.root, {**module, "id": "another-id"})

    def test_invalid_settings_and_hash_do_not_replace_working_files(self):
        module = self.module()
        for overrides in ({"context": True}, {"context": 0}, {"temperature": float("nan")},
                          {"max_tokens": 4096}, {"reasoning": True}, {"ubatch": 256}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                validate_settings(module, {**module["defaults"], **overrides})
        path = model_path(self.root, module)
        path.write_bytes(b"tampered")
        with self.assertRaises(RuntimeError), patch("urllib.request.urlopen") as network:
            ensure_model(self.root, module, allow_download=True)
        network.assert_not_called()
        self.assertEqual(path.read_bytes(), b"tampered")

    def test_context_budget_uses_settings_and_keeps_tool_groups_and_disk_history(self):
        module = self.module(tools=True)
        save_settings(self.root, {"model": module["id"], **module["defaults"],
                                 "context": 512, "max_tokens": 64, "temperature": 0.7})
        app = Assistant(self.root, 3)
        chat = app.new_chat()
        old = [{"role": "user", "content": "А" * 4000},
               {"role": "assistant", "content": None, "tool_calls": [{"id": "old", "function": {"name": "read_note", "arguments": "{}"}}]},
               {"role": "tool", "tool_call_id": "old", "content": "old result"},
               {"role": "assistant", "content": "Старый ответ"}]
        chat["messages"] = old
        app.save(chat)
        sent = []
        def api(port, route, body):
            if route == "/apply-template": return {"prompt": json.dumps(body, ensure_ascii=False)}
            if route == "/tokenize": return {"tokens": [1] * (len(body["content"]) // 4)}
            sent.append(copy.deepcopy(body))
            return {"choices": [{"message": {"role": "assistant", "content": "Новый ответ"}}]}
        with patch("assistant.http_json", side_effect=api):
            reply = app.ask(chat["id"], "Новый вопрос", False)
        self.assertEqual([m["role"] for m in sent[0]["messages"]], ["system", "user"])
        self.assertEqual(sent[0]["temperature"], 0.7)
        self.assertEqual(sent[0]["max_tokens"], 64)
        self.assertEqual(sent[0]["model"], MODEL_ALIAS)
        self.assertEqual(reply["messages"][:4], old)
        self.assertEqual(reply["context"]["omitted_messages"], 4)
        self.assertLessEqual(reply["context"]["input_tokens"], 512 - 64 - 64)

    def test_oversized_latest_turn_does_not_reach_generation(self):
        module = self.module()
        save_settings(self.root, {"model": module["id"], **module["defaults"], "context": 512, "max_tokens": 64})
        app = Assistant(self.root, 2)
        chat = app.new_chat()
        def api(port, route, body):
            if route == "/apply-template": return {"prompt": "fixture"}
            if route == "/tokenize": return {"tokens": [1] * 500}
            self.fail("Oversized request reached generation")
        with patch("assistant.http_json", side_effect=api), self.assertRaisesRegex(ValueError, "доступно"):
            app.ask(chat["id"], "Вопрос")
        self.assertEqual(app.load(chat["id"])["messages"], [])

    def test_multiturn_check_accepts_markdown_and_omitted_label(self):
        def api(port, route, body=None):
            if route == "/health": return {"status": "ok"}
            if route == "/v1/models": return {"data": [{"id": MODEL_ALIAS}]}
            return {"choices": [{"message": {"content": "Код: **4b71eb**."}}]}
        with patch("checks.http_json", side_effect=api), patch("checks.secrets.token_hex", return_value="4b71eb"):
            checks.api_check()

    def test_stage_one_keeps_documents_out_of_prompt_and_rejects_memory_write(self):
        app = Assistant(self.root, 1)
        app.save_memory("PRIVATE MEMORY")
        app.add_document("private.txt", "PRIVATE DOCUMENT")
        self.assertNotIn("PRIVATE", app.system_message()["content"])
        self.assertIsNone(app.sandbox)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(app))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/api/memory", data=b'{"text":"replace"}',
                    headers={"Host": "127.0.0.1:8080", "X-Local-Token": app.token})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with self.assertRaises(urllib.error.HTTPError) as error:
                opener.open(req)
            self.assertEqual(error.exception.code, 404)
            self.assertEqual((self.root / "data/memory.txt").read_text(), "PRIVATE MEMORY")
        finally:
            server.shutdown(); server.server_close(); thread.join()

    @unittest.skipIf(os.name == "nt", "POSIX subprocess fixture; native Windows still requires acceptance")
    def test_real_process_reload_rollback_and_settings_http(self):
        first = self.module("test-first")
        second = self.module("test-second")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        fixture = self.root / "fake-llama-server"
        fixture.write_text("#!" + sys.executable + "\n" + FIXTURE_SERVER)
        fixture.chmod(0o700)
        runtime = ModelRuntime(self.root, "cpu", "Vulkan0", 2, model=first["id"], port=port)
        class ProcessProbe:
            def __init__(self, pid): self.pid = pid
            def create_time(self): return 1.0
        with (patch("manage.server_binary", return_value=fixture),
              patch("manage.cpu_available_gib", return_value=32), patch("psutil.Process", ProcessProbe)):
            try:
                runtime.load()
                save_settings(self.root, runtime.settings)
                original_process = runtime.process
                candidate = {**runtime.settings, "temperature": 0.6, "max_tokens": 256}
                self.assertFalse(runtime.apply(candidate))
                self.assertIs(runtime.process, original_process)
                self.assertEqual(preferences(self.root)["profiles"][first["id"]]["temperature"], 0.6)
                with self.assertRaisesRegex(RuntimeError, "предыдущая модель восстановлена"):
                    runtime.apply({**candidate, "context": 8192})
                self.assertIsNotNone(original_process.poll())
                self.assertEqual(runtime.settings["context"], 4096)
                self.assertEqual(preferences(self.root)["profiles"][first["id"]]["context"], 4096)
                previous_process = runtime.process
                app = Assistant(self.root, 2, runtime=runtime)
                old_chat = app.new_chat()
                app.save_memory("KEEP MEMORY")
                app.add_document("keep.txt", "KEEP DOC")
                server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(app))
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                def request(route, body=None, token=True):
                    headers = {"Host": "127.0.0.1:8080", "Content-Type": "application/json"}
                    if token: headers["X-Local-Token"] = app.token
                    req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}" + route,
                          data=None if body is None else json.dumps(body).encode(), headers=headers)
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(req, timeout=15) as response: return json.load(response)
                try:
                    with self.assertRaises(urllib.error.HTTPError):
                        request("/api/settings", token=False)
                    result = request("/api/settings", {"model": second["id"], **second["defaults"]})
                    self.assertTrue(result["reloaded"])
                    self.assertEqual(result["chat"]["model"], second["id"])
                    self.assertIsNotNone(previous_process.poll())
                    self.assertEqual(request("/api/settings")["values"]["model"], second["id"])
                    reply = request("/api/chat", {"id": result["chat"]["id"], "text": "Тест"})
                    self.assertIn("тестового HTTP-сервера", reply["messages"][-1]["content"])
                    self.assertEqual(app.load(old_chat["id"])["model"], first["id"])
                    self.assertEqual((self.root / "data/memory.txt").read_text(), "KEEP MEMORY")
                    self.assertEqual((self.root / "data/documents/keep.txt").read_text(), "KEEP DOC")
                finally:
                    server.shutdown(); server.server_close(); thread.join()
            finally:
                runtime.closed.set()
                runtime.stop()
        events = [json.loads(line) for line in (self.root / "models/fixture-events.jsonl").read_text().splitlines()]
        self.assertEqual([e["context"] for e in events], [4096, 8192, 4096, 4096])
        self.assertEqual(len({e["pid"] for e in events}), 4)


if __name__ == "__main__":
    unittest.main()
