import json
import os
import tempfile
import unittest
from unittest import mock

from kongming_search import (
    build_kongming_evidence,
    build_kongming_reference_evidence,
    extract_kongming_search_terms,
)


class KongmingSearchTests(unittest.TestCase):
    def test_extracts_business_terms_from_natural_language(self):
        self.assertEqual(
            extract_kongming_search_terms('帮我查鉴宝活动关联的配置表和客户端入口'),
            ['鉴宝'],
        )
        self.assertEqual(
            extract_kongming_search_terms('九州风采活动关联哪些配置表'),
            ['九州风采'],
        )
        self.assertEqual(
            extract_kongming_search_terms('帮我查鉴宝活动，最多列出 3 张最相关的表'),
            ['鉴宝'],
        )
        self.assertEqual(
            extract_kongming_search_terms('跟钓鱼活动相关的 GM 命令'),
            ['钓鱼'],
        )
        self.assertEqual(
            extract_kongming_search_terms('每个赛季的火炉等级上限是多少'),
            ['赛季', '火炉', '等级', '上限', 'season', '篝火', 'level', 'limit'],
        )

    def test_builds_real_gm_command_candidates_for_command_question(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client_root = os.path.join(temp_dir, 'client')
            excel_root = os.path.join(temp_dir, 'excel')
            json_root = os.path.join(excel_root, 'json')
            commands_path = os.path.join(temp_dir, 'gm_commands.json')
            os.makedirs(client_root)
            os.makedirs(json_root)
            with open(commands_path, 'w', encoding='utf-8') as target:
                json.dump([
                    {
                        'id': 'doc_fish',
                        'name': 'fish',
                        'command': '#fish',
                        'category': '钓鱼',
                        'params': 'times=钓鱼次数 scene=钓鱼场景ID',
                        'example': '#fish 1 1',
                        'description': '钓鱼活动跑数测试',
                    },
                    {
                        'id': 'doc_fishall',
                        'name': 'fishall',
                        'command': '#fishall',
                        'category': '钓鱼',
                        'params': '',
                        'example': '#fishall',
                        'description': '一键完成所有钓鱼',
                    },
                    {
                        'id': 'doc_unrelated',
                        'name': 'level',
                        'command': '#level',
                        'category': '角色',
                        'params': 'level=等级',
                        'example': '#level 10',
                        'description': '修改角色等级',
                    },
                    {
                        'id': 'doc_activity',
                        'name': 'startact',
                        'command': '#startact',
                        'category': '活动',
                        'params': 'actId=活动ID',
                        'example': '#startact 1',
                        'description': '活动 GM 命令',
                    },
                ], target, ensure_ascii=False)

            evidence = build_kongming_evidence(
                '跟钓鱼活动相关的 GM 命令',
                client_root,
                excel_root,
                json_root,
                gm_commands_path=commands_path,
            )

        self.assertTrue(evidence['gm_command_search']['matched'])
        self.assertEqual(
            [item['command'] for item in evidence['gm_command_candidates']],
            ['#fish', '#fishall'],
        )
        self.assertEqual(evidence['gm_command_candidates'][0]['example'], '#fish 1 1')

    def test_does_not_add_gm_commands_to_non_command_question(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client_root = os.path.join(temp_dir, 'client')
            excel_root = os.path.join(temp_dir, 'excel')
            json_root = os.path.join(excel_root, 'json')
            commands_path = os.path.join(temp_dir, 'gm_commands.json')
            os.makedirs(client_root)
            os.makedirs(json_root)
            with open(commands_path, 'w', encoding='utf-8') as target:
                json.dump([{
                    'name': 'fish', 'command': '#fish', 'category': '钓鱼',
                }], target, ensure_ascii=False)

            evidence = build_kongming_evidence(
                '钓鱼活动关联哪些配置表',
                client_root,
                excel_root,
                json_root,
                gm_commands_path=commands_path,
            )

        self.assertEqual(evidence['gm_command_candidates'], [])

    def test_builds_table_and_client_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client_root = os.path.join(temp_dir, 'client')
            excel_root = os.path.join(temp_dir, 'excel')
            json_root = os.path.join(excel_root, 'json')
            table_dir = os.path.join(json_root, 'csv', 'common')
            client_dir = os.path.join(client_root, 'modules', 'logic', 'antique')
            os.makedirs(table_dir)
            os.makedirs(client_dir)

            table_path = os.path.join(table_dir, 'COA_Antique.json')
            with open(table_path, 'w', encoding='utf-8') as target:
                json.dump({
                    'sheets': [{
                        'name': 'Antique',
                        'rows': [
                            {'cells': {'A': 'id', 'B': 'name', 'C': 'openTime'}},
                            {'cells': {'A': '7000006', 'B': '鉴宝活动', 'C': '周一 08:00'}},
                        ],
                    }],
                }, target, ensure_ascii=False)

            client_path = os.path.join(client_dir, 'AntiqueView.ts')
            with open(client_path, 'w', encoding='utf-8') as target:
                target.write("const table = 'COA_Antique'; // 鉴宝活动入口\n")

            evidence = build_kongming_evidence(
                '帮我查鉴宝活动关联的配置表和客户端入口',
                client_root,
                excel_root,
                json_root,
            )

        self.assertEqual(evidence['keywords'], ['鉴宝'])
        self.assertEqual(evidence['table_candidates'][0]['xlsx_path'], 'csv/common/COA_Antique.xlsx')
        self.assertEqual(evidence['table_candidates'][0]['matched_rows'][0]['fields']['name'], '鉴宝活动')
        self.assertEqual(evidence['client_candidates'][0]['path'], 'modules/logic/antique/AntiqueView.ts')
        self.assertIn('鉴宝活动入口', evidence['client_candidates'][0]['snippets'][0]['text'])

    def test_derives_building_level_limits_by_season_from_complete_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client_root = os.path.join(temp_dir, 'client')
            excel_root = os.path.join(temp_dir, 'excel')
            json_root = os.path.join(excel_root, 'json')
            table_dir = os.path.join(json_root, 'csv', 'common')
            os.makedirs(client_root)
            os.makedirs(table_dir)
            with open(
                os.path.join(table_dir, 'COA_AB_BuildingLevel.json'),
                'w',
                encoding='utf-8',
            ) as target:
                json.dump({'sheets': [
                    {
                        'name': 'BuildingLevelB',
                        'rows': [
                            {'cells': {'A': 'id', 'B': 'build_id', 'C': 'build_name', 'D': 'build_lv'}},
                            {'cells': {'A': 26, 'B': 330101, 'C': '篝火', 'D': ';'.join(map(str, range(1, 61)))}} ,
                        ],
                    },
                    {
                        'name': 'BuildingLevelC',
                        'rows': [
                            {'cells': {'A': 'id', 'B': 'build_id', 'C': 'build_name', 'D': 'build_lv'}},
                            {'cells': {'A': 26, 'B': 330101, 'C': '篝火', 'D': ';'.join(map(str, range(1, 61)))}} ,
                        ],
                    },
                    {
                        'name': 'BuildingLevelD',
                        'rows': [
                            {'cells': {'A': 'id', 'B': 'build_id', 'C': 'build_name', 'D': 'build_lv'}},
                            {'cells': {'A': 26, 'B': 330101, 'C': '篝火', 'D': ';'.join(map(str, range(1, 61)))}} ,
                        ],
                    },
                    {
                        'name': 'BuildingAssociationB',
                        'rows': [
                            {'cells': {'A': 'id', 'B': 'build_level_id', 'D': 'season', 'F': 'build_name'}},
                            *[
                                {'cells': {
                                    'A': level - 30,
                                    'B': level,
                                    'D': 3 + (level - 31) // 6,
                                    'F': f'build_name_330101_{level}',
                                }}
                                for level in range(31, 61)
                            ],
                        ],
                    },
                ]}, target, ensure_ascii=False)

            evidence = build_kongming_evidence(
                '每个赛季的火炉等级上限是多少',
                client_root,
                excel_root,
                json_root,
            )

        fact = evidence['derived_facts'][0]
        self.assertEqual(fact['entity'], '篝火')
        self.assertEqual(fact['configured_max_level'], 60)
        self.assertEqual(fact['season_unlock_stages'][0], {
            'season': 3, 'min_level': 31, 'max_level': 36,
        })
        self.assertEqual(fact['season_level_limits'][0], {
            'season_from': 1, 'season_to': 2, 'max_level': 30,
        })
        self.assertEqual(fact['season_level_limits'][-1], {
            'season_from': 7, 'season_to': None, 'max_level': 60,
        })

    def test_compares_requested_release_branches_for_new_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client_root = os.path.join(temp_dir, 'client')
            excel_root = os.path.join(temp_dir, 'excel')
            json_root = os.path.join(excel_root, 'json')
            table_dir = os.path.join(json_root, 'csv', 'common')
            os.makedirs(table_dir)
            with open(
                os.path.join(table_dir, 'COA_ActivityFishingEvent.json'),
                'w',
                encoding='utf-8',
            ) as target:
                json.dump({
                    'sheets': [{
                        'name': 'FishingEventMain',
                        'rows': [
                            {'cells': {'A': 'COA_ActivityFishingEvent'}},
                            {'cells': {
                                'A': 'id',
                                'B': 'goldenFishMercyDrop',
                                'C': 'goldenFishMercyNum',
                                'D': 'crownMercy',
                            }},
                            {'cells': {'A': 1, 'B': 6341000, 'C': 15, 'D': '3|40'}},
                        ],
                    }],
                }, target, ensure_ascii=False)

            base_data = {
                'sheets': [{
                    'name': 'FishingEventMain',
                    'rows': [
                        {'cells': {
                            'A': 'id',
                            'B': 'goldenFishMercyNum',
                            'C': 'crownMercy',
                        }},
                        {'cells': {'A': 1, 'B': 15, 'C': '3|40'}},
                    ],
                }],
            }
            target_data = {
                'sheets': [{
                    'name': 'FishingEventMain',
                    'rows': [
                        {'cells': {
                            'A': 'id',
                            'B': 'goldenFishMercyDrop',
                            'C': 'goldenFishMercyNum',
                            'D': 'crownMercy',
                        }},
                        {'cells': {'A': 1, 'B': 6341000, 'C': 15, 'D': '3|40'}},
                    ],
                }],
            }
            with mock.patch('kongming_search._git_branch_refs', return_value=[
                'release/v20260813', 'release/v20260820',
            ]), mock.patch(
                'kongming_search._git_show_json',
                side_effect=lambda _root, ref, _path: (
                    base_data if ref == 'release/v20260813' else target_data
                ),
            ):
                evidence = build_kongming_evidence(
                    'COA_ActivityFishingEvent 配置表里的金冠保底字段，是 0820 分支上新增的吗',
                    client_root,
                    excel_root,
                    json_root,
                )

        comparison = evidence['branch_comparison']
        self.assertEqual(comparison['status'], 'compared')
        self.assertEqual(comparison['base_branch'], 'release/v20260813')
        self.assertEqual(comparison['target_branch'], 'release/v20260820')
        sheet = comparison['sheets'][0]
        self.assertEqual(sheet['added_fields'], ['goldenFishMercyDrop'])
        statuses = {item['field']: item['status'] for item in sheet['field_statuses']}
        self.assertEqual(statuses['goldenFishMercyNum'], 'existing_moved')
        self.assertEqual(statuses['crownMercy'], 'existing_moved')
        self.assertIn('goldenFishMercyDrop', comparison['conclusion'])

    def test_resolves_physical_rows_and_cross_table_drop_references(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            excel_root = os.path.join(temp_dir, 'excel')
            json_root = os.path.join(excel_root, 'json')
            table_dir = os.path.join(json_root, 'csv', 'common')
            os.makedirs(table_dir)

            activity_path = os.path.join(table_dir, 'COA_ActivityFishingEvent.json')
            with open(activity_path, 'w', encoding='utf-8') as target:
                json.dump({'sheets': [{
                    'name': 'FishingMain',
                    'rows': [
                        {'cells': {'A': 'FishingMain'}},
                        {'cells': {
                            'A': 'id',
                            'J': 'goldenFishMercyDrop',
                            'O': 'wonderlandMercyDrop',
                        }},
                        {'cells': {'A': 'int', 'J': 'string', 'O': 'string'}},
                        *[
                            {'cells': {}}
                            for _ in range(7)
                        ],
                        {'cells': {
                            'A': 1,
                            'J': 6343000,
                            'O': 6343010,
                        }},
                    ],
                }]}, target, ensure_ascii=False)

            drop_rows = [
                {'cells': {'A': 'Dropgroup'}},
                {'cells': {
                    'A': 'id',
                    'B': 'drop_name',
                    'D': 'droptype',
                    'L': 'item1',
                    'M': 'count1',
                    'N': 'weight1',
                }},
                *[
                    {'cells': {}}
                    for _ in range(19572 - 3)
                ],
                {'cells': {
                    'A': 6343000,
                    'B': '金鱼序列奖池',
                    'D': 5,
                    'L': 6343001,
                    'M': 1,
                    'N': 1,
                }},
                {'cells': {
                    'A': 6343001,
                    'B': '普通奖池',
                    'D': 5,
                    'L': 0,
                    'M': 1,
                    'N': 3,
                }},
                {'cells': {
                    'A': 6343002,
                    'B': '3中1奖池',
                    'D': 3,
                    'L': 0,
                    'M': 1,
                    'N': 6666,
                }},
                {'cells': {
                    'A': 6343003,
                    'B': '2中1奖池',
                    'D': 3,
                    'L': 0,
                    'M': 1,
                    'N': 5000,
                }},
                {'cells': {
                    'A': 6343004,
                    'B': '1中1奖池',
                    'D': 3,
                    'L': 1,
                    'M': 1,
                    'N': 10000,
                }},
                {'cells': {
                    'A': 6343010,
                    'B': '传说鱼池序列',
                    'D': 5,
                    'L': 6343016,
                    'M': 1,
                    'N': 1,
                }},
                {'cells': {
                    'A': 6343016,
                    'B': '普通奖池',
                    'D': 5,
                    'L': 0,
                    'M': 1,
                    'N': 17,
                }},
                {'cells': {
                    'A': 6343011,
                    'B': '5中1奖池',
                    'D': 3,
                    'L': 0,
                    'M': 1,
                    'N': 8000,
                }},
                {'cells': {
                    'A': 6343012,
                    'B': '4中1奖池',
                    'D': 3,
                    'L': 0,
                    'M': 1,
                    'N': 7500,
                }},
                {'cells': {
                    'A': 6343013,
                    'B': '3中1奖池',
                    'D': 3,
                    'L': 0,
                    'M': 1,
                    'N': 6666,
                }},
                {'cells': {
                    'A': 6343014,
                    'B': '2中1奖池',
                    'D': 3,
                    'L': 0,
                    'M': 1,
                    'N': 5000,
                }},
                {'cells': {
                    'A': 6343015,
                    'B': '1中1奖池',
                    'D': 3,
                    'L': 1,
                    'M': 1,
                    'N': 10000,
                }},
            ]
            with open(
                os.path.join(table_dir, 'SG_COA_Dropgroup.json'),
                'w',
                encoding='utf-8',
            ) as target:
                json.dump({'sheets': [{'name': 'Dropgroup', 'rows': drop_rows}]}, target, ensure_ascii=False)

            tables = [
                {
                    'json_path': 'csv/common/COA_ActivityFishingEvent.json',
                    'xlsx_path': 'csv/common/COA_ActivityFishingEvent.xlsx',
                    'sheets': ['FishingMain'],
                },
                {
                    'json_path': 'csv/common/SG_COA_Dropgroup.json',
                    'xlsx_path': 'csv/common/SG_COA_Dropgroup.xlsx',
                    'sheets': ['Dropgroup'],
                },
            ]
            evidence = build_kongming_reference_evidence(
                (
                    'COA_ActivityFishingEvent 的 goldenFishMercyDrop=6343000、'
                    'wonderlandMercyDrop=6343010，请确认 SG_COA_Dropgroup 物理行 19572~19583'
                ),
                '',
                excel_root,
                json_root,
                tables,
            )

        self.assertEqual(evidence['status'], 'confirmed')
        self.assertEqual(evidence['physical_row_query']['rows'], list(range(19572, 19584)))
        self.assertEqual(
            [row['id'] for row in evidence['target_rows']],
            [
                '6343000', '6343001', '6343002', '6343003', '6343004',
                '6343010', '6343016', '6343011', '6343012', '6343013',
                '6343014', '6343015',
            ],
        )
        self.assertTrue(any(
            header['name'] == 'drop_name'
            for header in evidence['target_headers']
        ))
        relations = {
            item['source_field']: item['target_rows'][0]['id']
            for item in evidence['references']
        }
        self.assertEqual(relations['J'], '6343000')
        self.assertEqual(relations['O'], '6343010')


if __name__ == '__main__':
    unittest.main()
