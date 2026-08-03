import os
import tempfile
import unittest
from unittest import mock

import server


def sample_artifact(name='测试点.xmind', artifact_format='xmind', content=b'xmind-content'):
    return {
        'filename': name,
        'mime': 'application/octet-stream',
        'format': artifact_format,
        'count': 3,
        'content': content,
    }


def sample_result(engine='Codex'):
    return {
        'ok': True,
        'engine': engine,
        'skill': 'qa-test-design',
        'generated_at': '2026-08-03 16:20:00',
        'structured': {
            'test_points': [{'id': 'TP-001', 'feature': '登录'}],
            'test_cases': [],
        },
    }


class QaHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.history_patch = mock.patch.object(server, 'QA_HISTORY_DIR', self.temp_dir.name)
        self.history_patch.start()

    def tearDown(self):
        self.history_patch.stop()
        self.temp_dir.cleanup()

    def test_history_survives_memory_reset_and_is_isolated_by_owner(self):
        artifact = server.save_qa_artifact(
            'user-a', sample_artifact(), sample_result(), 'points', '账号登录', 'codex'
        )

        items = server.list_qa_history('user-a')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['title'], '账号登录')
        self.assertEqual(items[0]['artifact']['id'], artifact['id'])

        detail = server.resolve_qa_history('user-a', artifact['id'])
        self.assertEqual(detail['result']['structured']['test_points'][0]['id'], 'TP-001')
        download = server.resolve_qa_artifact('user-a', artifact['id'])
        self.assertEqual(download['content'], b'xmind-content')

        self.assertEqual(server.list_qa_history('user-b'), [])
        self.assertIsNone(server.resolve_qa_history('user-b', artifact['id']))
        self.assertIsNone(server.resolve_qa_artifact('user-b', artifact['id']))
        self.assertFalse(server.delete_qa_history('user-b', artifact['id']))

    def test_delete_removes_metadata_and_artifact(self):
        artifact = server.save_qa_artifact(
            'user-a', sample_artifact(), sample_result(), 'points', '删除验证', 'codex'
        )
        owner_dir = server._qa_history_owner_dir('user-a')
        self.assertTrue(os.path.isfile(os.path.join(owner_dir, f"{artifact['id']}.json")))
        self.assertTrue(os.path.isfile(os.path.join(owner_dir, f"{artifact['id']}.xmind")))

        self.assertTrue(server.delete_qa_history('user-a', artifact['id']))
        self.assertEqual(server.list_qa_history('user-a'), [])
        self.assertFalse(os.path.exists(os.path.join(owner_dir, f"{artifact['id']}.json")))
        self.assertFalse(os.path.exists(os.path.join(owner_dir, f"{artifact['id']}.xmind")))

    def test_oldest_current_user_record_is_pruned_at_limit(self):
        with mock.patch.object(server, 'QA_ARTIFACT_MAX_PER_USER', 2):
            first = server.save_qa_artifact(
                'user-a', sample_artifact(content=b'first'), sample_result(), 'points', '第一条', 'codex'
            )
            second = server.save_qa_artifact(
                'user-a', sample_artifact(content=b'second'), sample_result(), 'points', '第二条', 'codex'
            )
            third = server.save_qa_artifact(
                'user-a', sample_artifact(content=b'third'), sample_result(), 'points', '第三条', 'codex'
            )

        ids = [item['id'] for item in server.list_qa_history('user-a')]
        self.assertEqual(ids, [third['id'], second['id']])
        self.assertIsNone(server.resolve_qa_artifact('user-a', first['id']))

    def test_invalid_history_id_is_rejected(self):
        self.assertIsNone(server.resolve_qa_history('user-a', '../outside'))
        self.assertIsNone(server.resolve_qa_artifact('user-a', 'not-an-id'))
        self.assertFalse(server.delete_qa_history('user-a', 'a' * 31))


if __name__ == '__main__':
    unittest.main()
