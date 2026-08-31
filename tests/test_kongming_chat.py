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
        self.assertIn('证据足够时直接推理并回答', prompt)
        self.assertIn('不得重新扫描整个 client_root 或 excel_root', prompt)

    def test_prompt_requires_real_gm_command_candidates(self):
        conversation = create_kongming_conversation('user-a', '钓鱼 GM 命令')
        evidence = {
            'keywords': ['钓鱼'],
            'table_candidates': [],
            'client_candidates': [],
            'gm_command_candidates': [{
                'command': '#fish',
                'category': '钓鱼',
                'params': 'times=钓鱼次数 scene=钓鱼场景ID',
                'example': '#fish 1 1',
                'description': '钓鱼活动跑数测试',
            }],
        }

        prompt = build_kongming_prompt(
            '跟钓鱼活动相关的 GM 命令',
            conversation,
            os.path.join(self.temp_dir.name, 'client'),
            os.path.join(self.temp_dir.name, 'excel'),
            os.path.join(self.temp_dir.name, 'excel', 'json'),
            evidence=evidence,
        )

        self.assertIn('#fish 1 1', prompt)
        self.assertIn('只能把候选中 command 字段的真实命令作为 GM 命令', prompt)
        self.assertIn('不能把客户端函数、协议名或配置表字段当成 GM 命令', prompt)

    def test_prompt_answers_rule_questions_before_listing_config_evidence(self):
        conversation = create_kongming_conversation('user-a', '火炉等级上限')
        evidence = {
            'keywords': ['赛季', '火炉', '等级上限'],
            'table_candidates': [{
                'xlsx_path': 'csv/common/COA_AB_BuildingLevel.xlsx',
                'sheets': ['BuildingLevelB', 'BuildingLevelC', 'BuildingLevelD'],
            }],
            'client_candidates': [],
            'gm_command_candidates': [],
        }

        prompt = build_kongming_prompt(
            '每个赛季的火炉等级上限是多少',
            conversation,
            os.path.join(self.temp_dir.name, 'client'),
            os.path.join(self.temp_dir.name, 'excel'),
            os.path.join(self.temp_dir.name, 'excel', 'json'),
            evidence=evidence,
        )

        self.assertIn('不要因为预检索里存在配置表候选', prompt)
        self.assertIn('直接结论 -> 必要的解释或依据 -> 仍存在的不确定性', prompt)
        self.assertIn('检查等级数组、有效行范围或最大等级记录', prompt)
        self.assertIn('规则问题重点说明最终规则或数值', prompt)

    def test_prompt_treats_cross_table_reference_evidence_as_confirmed(self):
        conversation = create_kongming_conversation(
            'user-a', '确认金鱼保底掉落组的具体内容'
        )
        evidence = {
            'keywords': ['goldenFishMercyDrop', '6343000'],
            'table_candidates': [],
            'client_candidates': [],
            'gm_command_candidates': [],
            'reference_evidence': {
                'status': 'confirmed',
                'target_table': 'csv/common/SG_COA_Dropgroup.xlsx',
                'target_headers': [{'column': 'B', 'name': 'drop_name'}],
                'target_rows': [{
                    'sheet': 'Dropgroup',
                    'physical_row': 19572,
                    'id': '6343000',
                    'fields': [{
                        'column': 'B', 'header': 'drop_name', 'value': '金鱼序列奖池',
                    }],
                }],
                'references': [{
                    'source_table': 'csv/common/COA_ActivityFishingEvent.xlsx',
                    'source_sheet': 'FishingEventMain',
                    'source_physical_row': 11,
                    'source_field': 'J',
                    'source_header': 'goldenFishMercyDrop',
                    'source_value': '6343000',
                    'target_table': 'csv/common/SG_COA_Dropgroup.xlsx',
                    'target_rows': [{
                        'sheet': 'Dropgroup',
                        'physical_row': 19572,
                        'id': '6343000',
                    }],
                }],
            },
        }

        prompt = build_kongming_prompt(
            '确认金鱼保底掉落组的具体内容',
            conversation,
            os.path.join(self.temp_dir.name, 'client'),
            os.path.join(self.temp_dir.name, 'excel'),
            os.path.join(self.temp_dir.name, 'excel', 'json'),
            evidence=evidence,
        )

        self.assertIn('reference_evidence', prompt)
        self.assertIn('必须直接回答“已确认”', prompt)
        self.assertIn('不得把它们写成“未确认”', prompt)

    def test_empty_and_oversized_questions_are_rejected(self):
        with self.assertRaises(ValueError):
            normalize_kongming_question('  ')
        with self.assertRaises(ValueError):
            normalize_kongming_question('x' * 4001)


if __name__ == '__main__':
    unittest.main()
