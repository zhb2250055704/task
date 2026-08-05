import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import server


class KongmingServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client_root = os.path.join(self.temp_dir.name, 'client')
        self.excel_root = os.path.join(self.temp_dir.name, 'excel')
        self.json_root = os.path.join(self.excel_root, 'json')
        os.makedirs(self.client_root)
        os.makedirs(self.json_root)
        self.patches = [
            mock.patch.object(server, 'KONGMING_CHAT_DIR', os.path.join(self.temp_dir.name, 'history')),
            mock.patch.object(server, 'KONGMING_CLIENT_ROOT', self.client_root),
            mock.patch.object(server, 'KONGMING_EXCEL_ROOT', self.excel_root),
            mock.patch.object(server, 'KONGMING_JSON_ROOT', self.json_root),
            mock.patch.object(server, 'KONGMING_CHAT_WORKSPACE', self.temp_dir.name),
            mock.patch.object(server, 'find_codex_cli', return_value=os.path.join(self.temp_dir.name, 'codex.exe')),
            mock.patch.object(server, 'find_kongming_cli', return_value=os.path.join(self.temp_dir.name, 'codex.exe')),
            mock.patch.object(server, 'prepare_kongming_bridge', return_value={'state': 'linked', 'ready': True}),
            mock.patch.object(
                server.subprocess,
                'run',
                return_value=SimpleNamespace(returncode=0, stdout='关联 COA_Activity.xlsx', stderr=''),
            ),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.temp_dir.cleanup()

    def test_chat_runs_in_read_only_mode_and_persists_answer(self):
        result = server.run_kongming_chat('user-a', '九州风采关联哪些配置表')

        self.assertTrue(result['ok'])
        self.assertEqual(result['answer'], '关联 COA_Activity.xlsx')
        self.assertEqual(len(result['conversation']['messages']), 2)
        call_args, call_kwargs = server.subprocess.run.call_args
        self.assertIn('read-only', call_args[0])
        self.assertIn('--ignore-user-config', call_args[0])
        self.assertIn('model_reasoning_effort="low"', call_args[0])
        self.assertIn('九州风采关联哪些配置表', call_kwargs['input'])
        self.assertEqual(call_kwargs['cwd'], self.temp_dir.name)

        history = server.get_kongming_chat_payload('user-a', result['conversation']['id'])
        self.assertEqual(history['conversation']['messages'][1]['role'], 'assistant')

    def test_unknown_conversation_is_rejected_without_leaking_lock(self):
        with self.assertRaises(ValueError):
            server.run_kongming_chat('user-a', '继续查询', 'missing-conversation')

        self.assertTrue(server._kongming_chat_lock.acquire(blocking=False))
        server._kongming_chat_lock.release()


if __name__ == '__main__':
    unittest.main()
