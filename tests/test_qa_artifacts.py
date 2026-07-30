import io
import json
import unittest
import zipfile

from openpyxl import load_workbook

from qa_artifacts import build_qa_artifact
from qa_local_engine import parse_qa_design_json


SAMPLE_DESIGN = {
    'title': '账号登录需求',
    'summary': {
        'objective': '验证账号登录功能',
        'scope': ['登录', '账号'],
        'highest_risk': '账号串号',
    },
    'requirements': [
        {'id': 'REQ-X', 'module': '登录', 'behavior': '有效账号可以登录'},
    ],
    'test_points': [
        {
            'id': 'POINT-X',
            'requirement_ids': ['REQ-X'],
            'module': '登录',
            'precondition': '账号已创建',
            'scenario': '使用有效账号登录',
            'type': '正向',
            'priority': 'P0',
            'target': '登录成功并进入角色界面',
            'source': '需求.docx',
        },
    ],
    'test_cases': [
        {
            'id': 'CASE-X',
            'requirement_ids': ['REQ-X'],
            'test_point_ids': ['POINT-X'],
            'module': '登录',
            'title': '有效账号登录',
            'preconditions': ['账号已创建'],
            'test_data': ['有效账号 A'],
            'steps': [
                {'action': '输入账号并登录', 'expected': '进入角色界面'},
            ],
            'priority': 'P0',
            'type': '正向',
            'automation': '高',
        },
    ],
    'traceability': [
        {
            'requirement_id': 'REQ-X',
            'test_point_ids': ['POINT-X'],
            'test_case_ids': ['CASE-X'],
            'coverage': '已覆盖',
        },
    ],
}


class QaArtifactTests(unittest.TestCase):
    def test_xmind_contains_structured_test_points(self):
        artifact = build_qa_artifact(SAMPLE_DESIGN, 'points', '账号登录需求')
        self.assertEqual(artifact['format'], 'xmind')
        self.assertEqual(artifact['count'], 1)
        with zipfile.ZipFile(io.BytesIO(artifact['content'])) as archive:
            self.assertTrue({'content.json', 'metadata.json', 'manifest.json'} <= set(archive.namelist()))
            content = json.loads(archive.read('content.json').decode('utf-8'))
        root = content[0]['rootTopic']
        self.assertEqual(root['title'], '账号登录需求')
        serialized = json.dumps(content, ensure_ascii=False)
        self.assertIn('使用有效账号登录', serialized)
        self.assertIn('登录成功并进入角色界面', serialized)

    def test_xlsx_contains_cases_steps_and_traceability(self):
        artifact = build_qa_artifact(SAMPLE_DESIGN, 'cases', '账号登录需求')
        self.assertEqual(artifact['format'], 'xlsx')
        workbook = load_workbook(io.BytesIO(artifact['content']))
        self.assertEqual(workbook.sheetnames, ['测试用例', '测试步骤', '需求追踪'])
        self.assertEqual(workbook['测试用例']['A2'].value, 'CASE-X')
        self.assertIn('输入账号并登录', workbook['测试用例']['J2'].value)
        self.assertEqual(workbook['测试步骤']['D2'].value, '进入角色界面')
        self.assertEqual(workbook['需求追踪']['D2'].value, '已覆盖')

    def test_codex_json_is_normalized_for_artifact_generation(self):
        raw = '```json\n' + json.dumps(SAMPLE_DESIGN, ensure_ascii=False) + '\n```'
        parsed = parse_qa_design_json(raw, mode='cases', title='账号登录需求')
        self.assertEqual(parsed['requirements'][0]['id'], 'REQ-001')
        self.assertEqual(parsed['test_points'][0]['id'], 'TP-001')
        self.assertEqual(parsed['test_cases'][0]['id'], 'TC-001')
        self.assertEqual(parsed['traceability'][0]['coverage'], '已覆盖')


if __name__ == '__main__':
    unittest.main()
