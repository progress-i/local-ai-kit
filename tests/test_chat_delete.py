"""Chat deletion: filesystem scope, confirmation, HTTP and streaming regression."""
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

KIT = Path(__file__).resolve().parents[1]
BASE = KIT.parent
sys.path.insert(0, str(KIT / 'app'))
from assistant import Assistant, handler_for
from lib.common import owned_root


class ChatDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=BASE)
        self.base = Path(self.temp.name)
        self.root = owned_root(self.base / 'LocalAISeries', create=True)
        self.app = Assistant(self.root, 2)
        self.first = self.app.new_chat()
        self.second = self.app.new_chat()
        self.app.save_memory('KEEP MEMORY')
        self.app.add_document('keep.txt', 'KEEP DOCUMENT')
        (self.root / 'data/workspace/keep.txt').write_text('KEEP NOTE')
        (self.root / 'models').mkdir()
        (self.root / 'models/keep.gguf').write_bytes(b'KEEP MODEL')

    def tearDown(self):
        self.temp.cleanup()

    def assert_kept(self):
        for relative, value in [('data/memory.txt', 'KEEP MEMORY'),
                                ('data/documents/keep.txt', 'KEEP DOCUMENT'),
                                ('data/workspace/keep.txt', 'KEEP NOTE'),
                                ('models/keep.gguf', 'KEEP MODEL')]:
            self.assertEqual((self.root / relative).read_text(), value)

    def test_delete_selected_and_continue_other_chat(self):
        self.assertEqual(self.app.delete_chats(self.first['id']), {'ok': True, 'deleted': 1})
        with self.assertRaises(FileNotFoundError):
            self.app.load(self.first['id'])
        self.assertEqual(self.app.load(self.second['id']), self.second)
        with patch.object(self.app, 'completion', return_value={'role': 'assistant', 'content': 'OK'}):
            result = self.app.ask(self.second['id'], 'Продолжим')
        self.assertEqual(result['messages'][-1]['content'], 'OK')
        self.assert_kept()

    def test_clear_only_chat_files_and_can_create_new(self):
        other = self.root / 'data/chats/keep.json'
        other.write_text('KEEP OTHER')
        self.assertEqual(self.app.delete_chats(all_chats=True)['deleted'], 2)
        self.assertEqual(other.read_text(), 'KEEP OTHER')
        self.assertEqual(self.app.delete_chats(all_chats=True)['deleted'], 0)
        new = self.app.new_chat()
        self.assertEqual(self.app.load(new['id'])['messages'], [])
        self.assert_kept()

    def test_invalid_or_missing_id_never_clears_history(self):
        for ident in (None, '', '../memory', '../' + self.first['id'], 7, {},
                      self.first['id'] + '.json', 'f' * 32):
            with self.subTest(ident=ident), self.assertRaises(ValueError):
                self.app.delete_chats(ident)
        self.assertEqual(len(list((self.root / 'data/chats').glob('*.json'))), 2)
        self.assert_kept()

    def test_symlink_folder_and_file_are_rejected_before_delete(self):
        folder = self.root / 'data/chats'
        outside = self.base / 'outside.json'
        outside.write_text('KEEP OUTSIDE')
        alias = folder / ('0' * 32 + '.json')
        try:
            alias.symlink_to(outside)
        except OSError:
            self.skipTest('Symlinks not available')
        with self.assertRaises(ValueError):
            self.app.delete_chats(all_chats=True)
        self.assertTrue((folder / (self.first['id'] + '.json')).exists())
        self.assertEqual(outside.read_text(), 'KEEP OUTSIDE')
        alias.unlink()
        folder.rename(folder.with_name('saved-chats'))
        folder.symlink_to(folder.with_name('saved-chats'), target_is_directory=True)
        with self.assertRaises(ValueError):
            self.app.delete_chats(self.first['id'])

    def test_pending_write_cannot_be_approved_after_deletion(self):
        self.app.stage = 3
        pending = self.app.load(self.first['id'])
        pending['pending'] = {'calls': [{'id': 'call', 'function': {
            'name': 'write_note', 'arguments': '{"name":"forbidden.txt","text":"NO"}'}}], 'remaining': 1}
        self.app.save(pending)
        self.app.delete_chats(pending['id'])
        with patch.object(self.app, 'tool_result') as execute:
            with self.assertRaises(FileNotFoundError):
                self.app.approve(pending['id'], True)
            execute.assert_not_called()
        self.assertFalse((self.root / 'data/workspace/forbidden.txt').exists())

    def test_streaming_reply_survives_and_blocks_deletion_until_done(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.app))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        release = threading.Event()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        headers = {'Host': '127.0.0.1:8080', 'X-Local-Token': self.app.token,
                   'Content-Type': 'application/json'}

        def completion(messages, agent, *, on_delta=None):
            on_delta('content', 'Первая ')
            if not release.wait(3):
                raise RuntimeError('Test stream was not released')
            on_delta('content', 'часть.')
            return {'role': 'assistant', 'content': 'Первая часть.'}

        def request(route, body):
            req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}' + route,
                                         data=json.dumps(body).encode(), headers=headers)
            return opener.open(req, timeout=5)

        try:
            with patch.object(self.app, 'completion', side_effect=completion):
                with request('/api/chat', {'id': self.first['id'], 'text': 'Вопрос', 'stream': True}) as response:
                    self.assertEqual(json.loads(response.readline())['type'], 'chat')
                    first = json.loads(response.readline())
                    self.assertEqual(first['type'], 'delta')
                    self.assertEqual(first['text'], 'Первая ')
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        request('/api/chats-clear', {'confirmed': True})
                    self.assertEqual(error.exception.code, 409)
                    release.set()
                    rest = [json.loads(line) for line in response]
                    self.assertEqual(rest[-1]['type'], 'done')
                    self.assertEqual(rest[-1]['chat']['messages'][-1]['content'], 'Первая часть.')
            with request('/api/chat-delete', {'id': self.first['id'], 'confirmed': True}) as response:
                self.assertEqual(json.load(response)['deleted'], 1)
            self.assertEqual(self.app.load(self.second['id'])['messages'], [])
            self.assert_kept()
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join()

    def test_http_confirmation_csrf_busy_and_valid_deletion(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.app))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def request(route, body, **headers):
            base_headers = {'Host': '127.0.0.1:8080', 'X-Local-Token': self.app.token,
                            'Content-Type': 'application/json'}
            base_headers.update(headers)
            req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}' + route,
                                         data=json.dumps(body).encode(), headers=base_headers)
            with opener.open(req, timeout=3) as response:
                return json.load(response)

        try:
            for route in ('/api/chat-delete', '/api/chats-clear'):
                for confirmed in (False, None, 'true', 1):
                    with self.subTest(route=route, confirmed=confirmed), self.assertRaises(urllib.error.HTTPError):
                        request(route, {'id': self.first['id'], 'confirmed': confirmed})
                with self.assertRaises(urllib.error.HTTPError):
                    request(route, {'confirmed': True}, **{'X-Local-Token': ''})
                with self.assertRaises(urllib.error.HTTPError):
                    request(route, {'confirmed': True}, Origin='https://example.invalid')
            with self.assertRaises(urllib.error.HTTPError):
                request('/api/chat-delete', {'confirmed': True})
            self.assertTrue((self.root / 'data/chats' / (self.first['id'] + '.json')).exists())
            with self.app.lock, self.assertRaises(urllib.error.HTTPError) as caught:
                request('/api/chats-clear', {'confirmed': True})
            self.assertEqual(caught.exception.code, 409)
            self.assertEqual(request('/api/chat-delete', {'id': self.first['id'], 'confirmed': True})['deleted'], 1)
            self.assertEqual(request('/api/chats-clear', {'confirmed': True})['deleted'], 1)
            self.assert_kept()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

if __name__ == "__main__":
    unittest.main()
