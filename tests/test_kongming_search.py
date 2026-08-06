import json
import os
import tempfile
import unittest

from kongming_search import build_kongming_evidence, extract_kongming_search_terms


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


if __name__ == '__main__':
    unittest.main()
