import os
import tempfile
import unittest

from kongming_chat import (
    append_kongming_message,
    build_kongming_prompt,
    create_kongming_conversation,
    delete_kongming_conversation,
    list_kongming_conversations,
    load_kongming_conversation,
    normalize_kongming_question,
    save_kongming_conversation,
)


class KongmingChatTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_conversation_is_persisted_and_isolated_by_owner(self):
        conversation = create_kongming_conversation('user-a', '九州风采关联哪些配置表')
        append_kongming_message(conversation, 'user', '九州风采关联哪些配置表')
        append_kongming_message(conversation, 'assistant', '关联 COA_Activity.xlsx')
        save_kongming_conversation(self.temp_dir.name, conversation)

        loaded = load_kongming_conversation(self.temp_dir.name, 'user-a', conversation['id'])
        self.assertEqual(loaded['title'], '九州风采关联哪些配置表')
        self.assertEqual(len(loaded['messages']), 2)
        self.assertIsNone(load_kongming_conversation(self.temp_dir.name, 'user-b', conversation['id']))
        self.assertEqual(list_kongming_conversations(self.temp_dir.name, 'user-a')[0]['message_count'], 2)

    def test_delete_only_removes_owner_conversation(self):
        conversation = create_kongming_conversation('user-a', '活动配置')
        save_kongming_conversation(self.temp_dir.name, conversation)

        self.assertFalse(delete_kongming_conversation(self.temp_dir.name, 'user-b', conversation['id']))
        self.assertTrue(delete_kongming_conversation(self.temp_dir.name, 'user-a', conversation['id']))
        self.assertIsNone(load_kongming_conversation(self.temp_dir.name, 'user-a', conversation['id']))

    def test_prompt_contains_read_only_roots_history_and_current_question(self):
        conversation = create_kongming_conversation('user-a', '活动配置')
        append_kongming_message(conversation, 'user', '先查活动入口')
        append_kongming_message(conversation, 'assistant', '入口是 ActivityView')

        prompt = build_kongming_prompt(
            '再查关联配置表',
            conversation,
            os.path.join(self.temp_dir.name, 'client'),
            os.path.join(self.temp_dir.name, 'excel'),
            os.path.join(self.temp_dir.name, 'excel', 'json'),
        )

        self.assertIn('只能读取和搜索本机文件', prompt)
        self.assertIn('先查活动入口', prompt)
        self.assertIn('再查关联配置表', prompt)
        self.assertIn('excel_json_mirror', prompt)

    def test_prompt_uses_local_evidence_without_rescanning_roots(self):
        conversation = create_kongming_conversation('user-a', '鉴宝活动')
        evidence = {
            'keywords': ['鉴宝'],
            'table_candidates': [{
                'xlsx_path': 'csv/common/COA_Antique.xlsx',
                'matched_rows': [{'sheet': 'Antique', 'row': 3}],
            }],
            'client_candidates': [],
        }

        prompt = build_kongming_prompt(
            '鉴宝活动关联哪些配置表',
            conversation,
            os.path.join(self.temp_dir.name, 'client'),
            os.path.join(self.temp_dir.name, 'excel'),
            os.path.join(self.temp_dir.name, 'excel', 'json'),
            evidence=evidence,
        )

        self.assertIn('COA_Antique.xlsx', prompt)
        self.assertIn('证据足够时直接回答', prompt)
        self.assertIn('不得重新扫描整个 client_root 或 excel_root', prompt)

    def test_empty_and_oversized_questions_are_rejected(self):
        with self.assertRaises(ValueError):
            normalize_kongming_question('  ')
        with self.assertRaises(ValueError):
            normalize_kongming_question('x' * 4001)


if __name__ == '__main__':
    unittest.main()
