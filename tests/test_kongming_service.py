import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import server


class KongmingServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        server._kongming_answer_cache.clear()
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
                server,
                'get_kongming_index_status',
                return_value={'ready': True, 'state': 'ready', 'generation': 7},
            ),
            mock.patch.object(
                server,
                'build_kongming_evidence',
                return_value={
                    'keywords': ['九州风采'],
                    'table_candidates': [{
                        'xlsx_path': 'csv/common/COA_Activity.xlsx',
                        'matched_rows': [],
                    }],
                    'client_candidates': [],
                    'table_search': {'source': 'index', 'index_generation': 7},
                },
            ),
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
        server._kongming_answer_cache.clear()
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
        self.assertIn('COA_Activity.xlsx', call_kwargs['input'])
        self.assertEqual(call_kwargs['cwd'], self.temp_dir.name)
        self.assertFalse(result['cached'])
        self.assertIn('search_duration_ms', result)
        self.assertIn('model_duration_ms', result)
        self.assertEqual(result['evidence']['table_candidate_count'], 1)
        self.assertEqual(result['message']['metadata']['table_search_source'], 'index')
        self.assertEqual(result['message']['metadata']['index_generation'], 7)
        self.assertEqual(
            server.build_kongming_evidence.call_args.kwargs['index_path'],
            server.KONGMING_INDEX_FILE,
        )
        self.assertEqual(
            server.build_kongming_evidence.call_args.kwargs['gm_commands_path'],
            server.DATA_FILE,
        )
        self.assertEqual(result['evidence']['gm_command_candidate_count'], 0)

        history = server.get_kongming_chat_payload('user-a', result['conversation']['id'])
        self.assertEqual(history['conversation']['messages'][1]['role'], 'assistant')

    def test_branch_comparison_evidence_is_kept_in_read_only_prompt(self):
        server.build_kongming_evidence.return_value = {
            'keywords': ['COA_ActivityFishingEvent', '0820'],
            'table_candidates': [{
                'xlsx_path': 'csv/common/COA_ActivityFishingEvent.xlsx',
                'matched_rows': [],
            }],
            'client_candidates': [],
            'branch_comparison': {
                'status': 'compared',
                'base_branch': 'release/v20260813',
                'target_branch': 'release/v20260820',
                'conclusion': 'goldenFishMercyDrop 为新增字段，crownMercy 在基线已存在',
            },
            'table_search': {'source': 'index', 'index_generation': 7},
        }
        result = server.run_kongming_chat(
            'user-a', 'COA_ActivityFishingEvent 配置表里的金冠保底字段，是 0820 分支上新增的吗'
        )

        self.assertTrue(result['ok'])
        prompt = server.subprocess.run.call_args.kwargs['input']
        self.assertIn('branch_comparison', prompt)
        self.assertIn('goldenFishMercyDrop', prompt)

    def test_unknown_conversation_is_rejected_without_leaking_lock(self):
        with self.assertRaises(ValueError):
            server.run_kongming_chat('user-a', '继续查询', 'missing-conversation')

        self.assertTrue(server._kongming_chat_lock.acquire(blocking=False))
        server._kongming_chat_lock.release()

    def test_repeated_new_question_uses_cached_answer(self):
        first = server.run_kongming_chat('user-a', '九州风采关联哪些配置表')
        second = server.run_kongming_chat('user-a', '  九州风采关联哪些配置表  ')

        self.assertFalse(first['cached'])
        self.assertTrue(second['cached'])
        self.assertEqual(second['answer'], first['answer'])
        self.assertEqual(second['duration_ms'], 0)
        self.assertTrue(second['message']['metadata']['cache_hit'])
        self.assertEqual(server.subprocess.run.call_count, 1)
        self.assertEqual(server.build_kongming_evidence.call_count, 1)

    def test_index_update_invalidates_answer_cache(self):
        server._kongming_answer_cache['cached'] = {'answer': 'old'}

        server._kongming_index_updated({
            'file_count': 2,
            'changed_count': 1,
            'removed_count': 0,
            'duration_ms': 10,
        })

        self.assertEqual(server._kongming_answer_cache, {})


if __name__ == '__main__':
    unittest.main()
