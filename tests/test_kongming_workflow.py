import os
import tempfile
import unittest
from unittest import mock

import kongming_workflow
import server


SAMPLE_TEXT = '''
帮我在ks环境https://zxty.tuyoo.com/keystone/applications?id=env-206&tab=7&projectId=project-1&cluster_name=%E8%85%BE%E8%AE%AF%E4%BA%91%E6%B5%8B%E8%AF%95%E9%9B%86%E7%BE%A4 中，
各个原服（165、181、311、249、137和141服）创建一个盟主号。执行成为天子命令。
只选中 Server_311（311）、Server_249（249）、Server_181（181Server_165（165）、Server_141（141）和 Server_137（137）执行备战活动脚本。
'''


def sample_catalog():
    return {
        'environments': [{
            'key': 'env-206',
            'raw_id': 'env-206',
            'app_id': 'env-206',
            'name': 'test-206-bzhd',
            'app_name': 'test-206-bzhd',
            'project_id': 'project-1',
            'cluster': '腾讯云测试集群',
            'status': 'APPLICATION_STATUS_RUNNING',
            'login_url': 'https://login-test-206.example.com',
        }],
    }


def sample_commands():
    return [{
        'id': kongming_workflow.KONGMING_COMMAND_ID,
        'name': '成为王盟(S1)/天子',
        'command': '#setKingAppointBegin',
    }]


def sample_scripts():
    return [{
        'id': kongming_workflow.KONGMING_SCRIPT_ID,
        'name': '备战活动脚本',
        'content': "return '1';",
    }]


def sample_reward_catalog():
    env = {
        'key': 'env-reward-202',
        'raw_id': 'env-reward-202',
        'app_id': 'env-reward-202',
        'name': 'test-202-26a3a3c6',
        'app_name': 'test-202-26a3a3c6',
        'project_id': 'project-1',
        'cluster': '腾讯云测试集群',
        'status': 'APPLICATION_STATUS_RUNNING',
        'login_url': 'https://login-test-202-26a3a3c6-sanguo2-sanguo2-test-138.sg2txxj.tuyoodev.cn',
        'links': [
            'https://gm-test-202-26a3a3c6-sanguo2-sanguo2-test-138.sg2txxj.tuyoodev.cn',
        ],
    }
    env['accounts'] = [{
        'environment_key': env['key'],
        'cache_id': 'cache-reward-1',
        'account_name': '101.A.account.721495',
        'account_label': '101.A.account.721495',
        'role_id': '101000001',
        'server_id': '101',
        'operation_time': '2026-08-10T10:00:00',
    }]
    return {'environments': [env]}


def sample_bulk_reward_catalog(account_count=3):
    catalog = sample_reward_catalog()
    environment = catalog['environments'][0]
    environment['raw_id'] = 'd7c5ef7a-b9c7-41f0-8105-5427c2fc3eac'
    environment['app_id'] = 'd7c5ef7a-b9c7-41f0-8105-5427c2fc3eac'
    environment['accounts'] = [
        {
            'environment_key': environment['key'],
            'cache_id': f'cache-reward-{index}',
            'account_name': f'101.A.account.{700000 + index}',
            'account_label': f'角色{index}',
            'role_id': f'10100000{index}',
            'server_id': '101',
            'operation_time': f'2026-08-10T10:00:0{index}',
        }
        for index in range(1, account_count + 1)
    ]
    return catalog


BULK_REWARD_TEXT = (
    'https://zxty.tuyoo.com/keystone/applications?'
    'id=d7c5ef7a-b9c7-41f0-8105-5427c2fc3eac&tab=7&'
    'projectId=279ff321-c749-4cd2-aa83-2d8f995b6812&cluster_name=腾讯云测试集群\n'
    '给这个KS环境下的3个账号，每个账号发1亿元宝'
)


def sample_reward_commands():
    return [{
        'id': kongming_workflow.KONGMING_REWARD_COMMAND_ID,
        'name': '添加货币',
        'command': '#money',
    }]


def sample_account_commands():
    return sample_reward_commands() + [{
        'id': 'doc_setviplevel',
        'name': 'setVipLevel',
        'command': '#setVipLevel',
        'category': 'VIP',
        'params': 'level=等级（1-100，具体范围参考功能配置）',
        'example': '#setVipLevel 1',
        'description': '设置VIP等级',
    }]


class KongmingWorkflowParsingTests(unittest.TestCase):
    def test_url_and_typo_tolerant_servers_are_parsed_exactly(self):
        target = kongming_workflow.parse_ks_application_url(SAMPLE_TEXT)
        account_servers, script_servers = kongming_workflow.parse_workflow_servers(SAMPLE_TEXT)

        self.assertEqual(target['app_id'], 'env-206')
        self.assertEqual(target['project_id'], 'project-1')
        self.assertEqual(target['cluster_name'], '腾讯云测试集群')
        self.assertEqual(account_servers, ['165', '181', '311', '249', '137', '141'])
        self.assertEqual(script_servers, ['311', '249', '181', '165', '141', '137'])

    def test_script_scope_cannot_widen_account_scope(self):
        text = SAMPLE_TEXT.replace('Server_137（137）', 'Server_999（999）')
        with self.assertRaisesRegex(ValueError, '脚本目标不在'):
            kongming_workflow.parse_workflow_servers(text)

    def test_plan_uses_stable_command_and_script_ids_without_executing(self):
        workflow = kongming_workflow.build_kongming_workflow(
            'owner-1', SAMPLE_TEXT, sample_catalog(), sample_commands(), sample_scripts()
        )

        self.assertEqual(workflow['state'], 'pending_confirmation')
        self.assertEqual(workflow['command']['id'], kongming_workflow.KONGMING_COMMAND_ID)
        self.assertEqual(workflow['script']['id'], kongming_workflow.KONGMING_SCRIPT_ID)
        self.assertIn('6服盟主备战', workflow['title'])
        self.assertEqual(workflow['steps'][1]['title'], '在 6 个原服创建盟主号')
        self.assertEqual(len(workflow['steps']), 6)
        self.assertTrue(all(step['status'] == 'pending' for step in workflow['steps']))
        self.assertEqual(workflow['runtime']['created_accounts'], [])

    def test_workflow_storage_is_isolated_by_owner(self):
        workflow = kongming_workflow.build_kongming_workflow(
            'owner-1', SAMPLE_TEXT, sample_catalog(), sample_commands(), sample_scripts()
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            kongming_workflow.save_kongming_workflow(temp_dir, workflow)
            self.assertIsNotNone(kongming_workflow.load_kongming_workflow(temp_dir, 'owner-1', workflow['id']))
            self.assertIsNone(kongming_workflow.load_kongming_workflow(temp_dir, 'owner-2', workflow['id']))

    def test_reward_request_from_login_url_builds_confirmable_workflow(self):
        text = (
            '环境：https://login-test-202-26a3a3c6-sanguo2-sanguo2-test-138.sg2txxj.tuyoodev.cn\n'
            '账号：101.A.account.721495\n'
            '给这个账号发 1亿 元宝'
        )
        workflow = kongming_workflow.build_kongming_workflow(
            'owner-1', text, sample_reward_catalog(), sample_reward_commands(), []
        )

        self.assertEqual(workflow['type'], kongming_workflow.KONGMING_REWARD_WORKFLOW_TYPE)
        self.assertEqual(workflow['state'], 'pending_confirmation')
        self.assertEqual(workflow['environment']['key'], 'env-reward-202')
        self.assertEqual(workflow['reward']['amount'], 100000000)
        self.assertEqual(workflow['reward']['currency_id'], '43')
        self.assertEqual(workflow['command']['command'], '#money 43 100000000')
        self.assertEqual(workflow['targets'][0]['cache_id'], 'cache-reward-1')
        self.assertEqual([step['id'] for step in workflow['steps']], [
            'resolve_reward_targets',
            'execute_reward_command',
        ])

    def test_reward_request_requires_cached_account(self):
        text = (
            '环境：https://login-test-202-26a3a3c6-sanguo2-sanguo2-test-138.sg2txxj.tuyoodev.cn\n'
            '账号：101.A.account.999999，发100元宝'
        )
        with self.assertRaisesRegex(ValueError, '没有找到账号'):
            kongming_workflow.build_kongming_workflow(
                'owner-1', text, sample_reward_catalog(), sample_reward_commands(), []
            )

    def test_bulk_reward_request_from_ks_url_builds_three_target_preview(self):
        catalog = sample_bulk_reward_catalog()

        self.assertTrue(kongming_workflow.is_kongming_reward_workflow_request(BULK_REWARD_TEXT))
        environment = kongming_workflow.find_kongming_environment(catalog, BULK_REWARD_TEXT)
        workflow = kongming_workflow.build_kongming_workflow(
            'owner-1', BULK_REWARD_TEXT, catalog, sample_reward_commands(), []
        )

        self.assertEqual(environment['key'], 'env-reward-202')
        self.assertEqual(workflow['state'], 'pending_confirmation')
        self.assertEqual(len(workflow['targets']), 3)
        self.assertEqual(workflow['command']['command'], '#money 43 100000000')

    def test_generic_vip_request_builds_validated_account_command_workflow(self):
        text = BULK_REWARD_TEXT.splitlines()[0] + '\n给这3个账号，每个账号的VIP等级设置为12级'
        workflow = kongming_workflow.build_kongming_workflow(
            'owner-1', text, sample_bulk_reward_catalog(), sample_account_commands(), []
        )

        self.assertEqual(
            workflow['type'], kongming_workflow.KONGMING_ACCOUNT_COMMAND_WORKFLOW_TYPE
        )
        self.assertEqual(workflow['state'], 'pending_confirmation')
        self.assertEqual(workflow['command']['id'], 'doc_setviplevel')
        self.assertEqual(workflow['command']['command'], '#setVipLevel 12')
        self.assertEqual(len(workflow['targets']), 3)
        self.assertEqual([step['id'] for step in workflow['steps']], [
            'resolve_account_targets',
            'execute_account_command',
        ])

    def test_generic_command_match_accepts_natural_action_synonyms(self):
        text = BULK_REWARD_TEXT.splitlines()[0] + '\n把这3个账号的VIP都升到12级'
        workflow = kongming_workflow.build_kongming_workflow(
            'owner-1', text, sample_bulk_reward_catalog(), sample_account_commands(), []
        )

        self.assertEqual(workflow['command']['id'], 'doc_setviplevel')
        self.assertEqual(workflow['command']['command'], '#setVipLevel 12')

    def test_follow_up_action_inherits_only_the_latest_workflow_scope(self):
        previous = kongming_workflow.build_kongming_workflow(
            'owner-1', BULK_REWARD_TEXT, sample_bulk_reward_catalog(), sample_reward_commands(), []
        )
        conversation = {
            'messages': [{
                'role': 'assistant',
                'content': '任务预览',
                'metadata': {'workflow_id': previous['id']},
            }],
        }
        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(server, 'KONGMING_WORKFLOW_DIR', temp_dir):
            kongming_workflow.save_kongming_workflow(temp_dir, previous)
            expanded = server._kongming_workflow_question_with_context(
                'owner-1', '给这3个账号，每个账号的VIP等级设置为12级', conversation
            )

        self.assertIn(previous['environment']['source_url'], expanded)
        self.assertIn(previous['targets'][0]['account_name'], expanded)
        self.assertTrue(kongming_workflow.is_kongming_workflow_request(expanded))

    def test_read_only_follow_up_does_not_inherit_workflow_scope(self):
        previous = kongming_workflow.build_kongming_workflow(
            'owner-1', BULK_REWARD_TEXT, sample_bulk_reward_catalog(), sample_reward_commands(), []
        )
        conversation = {
            'messages': [{
                'role': 'assistant',
                'content': '任务预览',
                'metadata': {'workflow_id': previous['id']},
            }],
        }
        question = '钓鱼篓第四期活动的配置表是哪一张'
        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(server, 'KONGMING_WORKFLOW_DIR', temp_dir):
            kongming_workflow.save_kongming_workflow(temp_dir, previous)
            expanded = server._kongming_workflow_question_with_context(
                'owner-1', question, conversation
            )

        self.assertEqual(expanded, question)
        self.assertFalse(kongming_workflow.is_kongming_workflow_request(expanded))

    def test_bulk_reward_count_mismatch_stops_preview(self):
        with self.assertRaisesRegex(ValueError, '识别到 2 个唯一账号.*请求中的 3 个账号不一致'):
            kongming_workflow.build_kongming_workflow(
                'owner-1', BULK_REWARD_TEXT, sample_bulk_reward_catalog(2),
                sample_reward_commands(), []
            )

    def test_vague_reward_scope_is_not_routed_to_execution(self):
        text = (
            '环境：https://login-test-202-26a3a3c6-sanguo2-sanguo2-test-138.sg2txxj.tuyoodev.cn\n'
            '给账号发1亿元宝'
        )

        self.assertFalse(kongming_workflow.is_kongming_reward_workflow_request(text))

    def test_bulk_reward_target_limit_is_enforced(self):
        text = BULK_REWARD_TEXT.replace('3个账号', '全部账号')
        with self.assertRaisesRegex(ValueError, '最多允许 20 个账号'):
            kongming_workflow.build_kongming_workflow(
                'owner-1', text, sample_bulk_reward_catalog(21), sample_reward_commands(), []
            )

    def test_reward_plan_uses_global_catalog_without_request_time_network_calls(self):
        catalog = sample_bulk_reward_catalog(3)
        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(server, 'KONGMING_WORKFLOW_DIR', temp_dir), \
                mock.patch.object(server, 'current_cocos_targets') as current_targets, \
                mock.patch.object(server, 'ks_catalog_with_online', return_value=catalog), \
                mock.patch.object(server, 'ks_refresh_environment_accounts') as refresh, \
                mock.patch.object(server, 'load_data', return_value=sample_reward_commands()), \
                mock.patch.object(server, 'load_scripts', return_value=[]):
            workflow = server.create_kongming_workflow_plan('owner-1', BULK_REWARD_TEXT)

        current_targets.assert_not_called()
        refresh.assert_not_called()
        self.assertEqual(workflow['state'], 'pending_confirmation')
        self.assertEqual(len(workflow['targets']), 3)

    def test_global_account_catalog_refreshes_all_environments_in_parallel(self):
        environments = sample_bulk_reward_catalog(3)['environments']
        environments.append({
            **sample_reward_catalog()['environments'][0],
            'key': 'env-reward-203',
        })
        cache = {'catalog': {'environments': environments}}
        with mock.patch.object(server, 'load_ks_config', return_value={'token': 'token'}), \
                mock.patch.object(server, 'ks_token_status', return_value={
                    'configured': True,
                    'expired': False,
                }), \
                mock.patch.object(server, '_load_json_object', return_value=cache), \
                mock.patch.object(server, 'ks_refresh_environment_accounts', return_value={}) as refresh:
            result = server.refresh_kongming_account_catalog()

        self.assertTrue(result['ok'])
        self.assertEqual(result['success_count'], 2)
        self.assertCountEqual(
            [call.args[0] for call in refresh.call_args_list],
            ['env-reward-202', 'env-reward-203'],
        )

    def test_pending_reward_command_can_be_edited_and_persisted(self):
        text = (
            '环境：https://login-test-202-26a3a3c6-sanguo2-sanguo2-test-138.sg2txxj.tuyoodev.cn\n'
            '账号：101.A.account.721495，发100元宝'
        )
        workflow = kongming_workflow.build_kongming_workflow(
            'owner-1', text, sample_reward_catalog(), sample_reward_commands(), []
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            kongming_workflow.save_kongming_workflow(temp_dir, workflow)
            updated = kongming_workflow.update_kongming_workflow_command(
                temp_dir, 'owner-1', workflow['id'], '#money 43 12345', 'admin'
            )
            persisted = kongming_workflow.load_kongming_workflow(
                temp_dir, 'owner-1', workflow['id']
            )

        self.assertEqual(updated['command']['command'], '#money 43 12345')
        self.assertEqual(persisted['reward']['amount'], 12345)
        self.assertEqual(persisted['reward']['amount_text'], '12,345')
        self.assertEqual(persisted['steps'][1]['title'], '并行发放 12,345 元宝')
        self.assertEqual(persisted['edits'][0]['operator'], 'admin')

    def test_reward_command_edit_rejects_other_commands_and_started_tasks(self):
        text = (
            '环境：https://login-test-202-26a3a3c6-sanguo2-sanguo2-test-138.sg2txxj.tuyoodev.cn\n'
            '账号：101.A.account.721495，发100元宝'
        )
        workflow = kongming_workflow.build_kongming_workflow(
            'owner-1', text, sample_reward_catalog(), sample_reward_commands(), []
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            kongming_workflow.save_kongming_workflow(temp_dir, workflow)
            with self.assertRaisesRegex(ValueError, '格式应为'):
                kongming_workflow.update_kongming_workflow_command(
                    temp_dir, 'owner-1', workflow['id'], '#unknown 43 1', 'admin'
                )
            workflow['state'] = 'running'
            kongming_workflow.save_kongming_workflow(temp_dir, workflow)
            with self.assertRaisesRegex(ValueError, '等待确认'):
                kongming_workflow.update_kongming_workflow_command(
                    temp_dir, 'owner-1', workflow['id'], '#money 43 1', 'admin'
                )


class KongmingWorkflowExecutionTests(unittest.TestCase):
    def test_account_retry_creates_only_missing_servers(self):
        workflow = kongming_workflow.build_kongming_workflow(
            'owner-1', SAMPLE_TEXT, sample_catalog(), sample_commands(), sample_scripts()
        )
        workflow['account_servers'] = ['165', '181', '311']
        workflow['runtime']['account_baseline'] = {
            server_id: [] for server_id in workflow['account_servers']
        }
        workflow['runtime']['account_baseline_captured'] = True
        workflow['runtime']['season_server_id'] = '9001'

        def account(server_id):
            return {
                'cache_id': 'cache-' + server_id,
                'account_name': 'account-' + server_id,
                'role_name': '盟主-' + server_id,
                'role_id': 'role-' + server_id,
                'server_id': server_id,
                'source_case_name': server.KS_LOGIN_CASE_NAME,
            }

        cached_environment = {
            **sample_catalog()['environments'][0],
            'accounts': [],
        }
        refresh_results = [
            {**cached_environment, 'accounts': [account('165')]},
            {**cached_environment, 'accounts': [account('165'), account('181'), account('311')]},
        ]

        with mock.patch.object(server, 'ks_cached_environment', return_value=cached_environment), \
                mock.patch.object(server, 'ks_refresh_environment_accounts', side_effect=refresh_results), \
                mock.patch.object(server, 'ks_create_alliance_accounts', return_value={
                    'completed': True,
                    'event_count': 1,
                }) as create_accounts, \
                mock.patch.object(server, 'save_kongming_workflow', side_effect=lambda _base, value: value):
            result = server._workflow_create_accounts(workflow)

        create_accounts.assert_called_once_with(cached_environment, '9001', ['181', '311'])
        self.assertEqual(result['msg'], 'KS 创建请求已完成，本次补建 2 个原服账号')
        self.assertEqual(
            [item['server_id'] for item in workflow['runtime']['created_accounts']],
            ['165', '181', '311'],
        )

    def test_confirmation_runs_steps_in_order(self):
        workflow = kongming_workflow.build_kongming_workflow(
            'owner-1', SAMPLE_TEXT, sample_catalog(), sample_commands(), sample_scripts()
        )
        calls = []

        def handler(step_id):
            def run(_workflow):
                calls.append(step_id)
                return {'msg': step_id}
            return run

        handlers = {step['id']: handler(step['id']) for step in workflow['steps']}
        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(server, 'KONGMING_WORKFLOW_DIR', temp_dir), \
                mock.patch.object(server, 'KONGMING_WORKFLOW_STEP_HANDLERS', handlers):
            kongming_workflow.save_kongming_workflow(temp_dir, workflow)
            server.start_kongming_workflow('owner-1', workflow['id'])
            thread_workflow = None
            for _ in range(100):
                thread_workflow = server.get_kongming_workflow('owner-1', workflow['id'])
                if thread_workflow.get('state') == 'completed':
                    break
                import time
                time.sleep(0.01)

        self.assertEqual(thread_workflow['state'], 'completed')
        self.assertEqual(calls, [step['id'] for step in workflow['steps']])

    def test_retry_skips_completed_steps(self):
        workflow = kongming_workflow.build_kongming_workflow(
            'owner-1', SAMPLE_TEXT, sample_catalog(), sample_commands(), sample_scripts()
        )
        workflow['state'] = 'failed'
        workflow['confirmed_at'] = '2026-08-07 12:00:00'
        workflow['steps'][0]['status'] = 'completed'
        workflow['steps'][1]['status'] = 'failed'
        calls = []
        handlers = {
            step['id']: (lambda _workflow, step_id=step['id']: calls.append(step_id) or {'msg': step_id})
            for step in workflow['steps']
        }
        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(server, 'KONGMING_WORKFLOW_DIR', temp_dir), \
                mock.patch.object(server, 'KONGMING_WORKFLOW_STEP_HANDLERS', handlers):
            kongming_workflow.save_kongming_workflow(temp_dir, workflow)
            server.start_kongming_workflow('owner-1', workflow['id'], retry=True)
            retried = None
            for _ in range(100):
                retried = server.get_kongming_workflow('owner-1', workflow['id'])
                if retried.get('state') == 'completed':
                    break
                import time
                time.sleep(0.01)

        self.assertEqual(retried['state'], 'completed')
        self.assertNotIn('resolve_environment', calls)
        self.assertEqual(calls[0], 'create_accounts')

    def test_sync_failure_retry_reconciles_account_creation_first(self):
        workflow = kongming_workflow.build_kongming_workflow(
            'owner-1', SAMPLE_TEXT, sample_catalog(), sample_commands(), sample_scripts()
        )
        workflow['state'] = 'failed'
        workflow['confirmed_at'] = '2026-08-07 12:00:00'
        workflow['steps'][0]['status'] = 'completed'
        workflow['steps'][1]['status'] = 'completed'
        workflow['steps'][2]['status'] = 'failed'
        calls = []
        handlers = {
            step['id']: (lambda _workflow, step_id=step['id']: calls.append(step_id) or {'msg': step_id})
            for step in workflow['steps']
        }
        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(server, 'KONGMING_WORKFLOW_DIR', temp_dir), \
                mock.patch.object(server, 'KONGMING_WORKFLOW_STEP_HANDLERS', handlers):
            kongming_workflow.save_kongming_workflow(temp_dir, workflow)
            server.start_kongming_workflow('owner-1', workflow['id'], retry=True)
            retried = None
            for _ in range(100):
                retried = server.get_kongming_workflow('owner-1', workflow['id'])
                if retried.get('state') == 'completed':
                    break
                import time
                time.sleep(0.01)

        self.assertEqual(retried['state'], 'completed')
        self.assertEqual(calls[0:2], ['create_accounts', 'sync_accounts'])

    def test_reward_targets_are_resolved_from_current_online_clients(self):
        text = (
            '环境：https://login-test-202-26a3a3c6-sanguo2-sanguo2-test-138.sg2txxj.tuyoodev.cn\n'
            '账号：101.A.account.721495\n'
            '发 1亿 元宝'
        )
        workflow = kongming_workflow.build_kongming_workflow(
            'owner-1', text, sample_reward_catalog(), sample_reward_commands(), []
        )
        online_target = {
            'id': 'client-1',
            'connection_id': 'client-1',
            'client_id': 'client-1',
            'port': '5101',
            'role_id': '101000001',
            'server_id': '101',
            'account_name': '101.A.account.721495',
            'account_label': '101.A.account.721495',
            'environment_url': 'https://login-test-202-26a3a3c6-sanguo2-sanguo2-test-138.sg2txxj.tuyoodev.cn',
            'dispatchable': True,
        }

        with mock.patch.object(server, 'current_cocos_targets', return_value=[online_target]), \
                mock.patch.object(server, 'ks_cached_environment', return_value=sample_reward_catalog()['environments'][0]), \
                mock.patch.object(server, 'save_kongming_workflow', side_effect=lambda _base, value: value):
            result = server._workflow_resolve_reward_targets(workflow)

        self.assertEqual(result['channel'], 'cocos')
        self.assertEqual(workflow['runtime']['online_targets'][0]['connection_id'], 'client-1')

    def test_reward_command_executes_through_current_online_targets(self):
        text = (
            '环境：https://login-test-202-26a3a3c6-sanguo2-sanguo2-test-138.sg2txxj.tuyoodev.cn\n'
            '账号：101.A.account.721495\n'
            '发 1亿 元宝'
        )
        workflow = kongming_workflow.build_kongming_workflow(
            'owner-1', text, sample_reward_catalog(), sample_reward_commands(), []
        )
        workflow['runtime']['online_targets'] = [{
            'id': 'client-1',
            'connection_id': 'client-1',
            'client_id': 'client-1',
            'port': '5101',
            'cache_id': 'cache-reward-1',
            'account_name': '101.A.account.721495',
            'role_id': '101000001',
            'server_id': '101',
            'environment_url': 'https://login-test-202-26a3a3c6-sanguo2-sanguo2-test-138.sg2txxj.tuyoodev.cn',
            'dispatchable': True,
        }]
        cocos_result = {
            'ok': True,
            'success_count': 1,
            'target_count': 1,
            'batch_results': [{
                'ok': True,
                'target': {'id': 'client-1'},
            }],
        }
        with mock.patch.object(server, 'execute_gm_commands', return_value=cocos_result) as execute_gm, \
                mock.patch.object(server, 'save_kongming_workflow', side_effect=lambda _base, value: value):
            result = server._workflow_execute_reward_command(workflow)

        execute_gm.assert_called_once_with(
            ['#money 43 100000000'],
            target_specs=workflow['runtime']['online_targets'],
            ks_targets=[],
        )
        self.assertEqual(result['success_count'], 1)
        self.assertEqual(workflow['runtime']['command_completed_cache_ids'], ['cache:cache-reward-1'])

    def test_generic_account_command_uses_cocos_and_ks_for_mixed_presence(self):
        text = BULK_REWARD_TEXT.splitlines()[0] + '\n给这3个账号，每个账号的VIP等级设置为12级'
        catalog = sample_bulk_reward_catalog()
        workflow = kongming_workflow.build_kongming_workflow(
            'owner-1', text, catalog, sample_account_commands(), []
        )
        first = workflow['targets'][0]
        online_target = {
            'id': 'client-vip-1',
            'connection_id': 'client-vip-1',
            'client_id': 'client-vip-1',
            'port': '5101',
            'role_id': first['role_id'],
            'server_id': first['server_id'],
            'account_name': first['account_name'],
            'environment_url': catalog['environments'][0]['login_url'],
            'dispatchable': True,
        }
        with mock.patch.object(server, 'current_cocos_targets', return_value=[online_target]), \
                mock.patch.object(server, 'ks_cached_environment', return_value=catalog['environments'][0]), \
                mock.patch.object(server, 'save_kongming_workflow', side_effect=lambda _base, value: value):
            resolved = server._workflow_resolve_reward_targets(workflow)

        self.assertEqual(resolved['client_count'], 1)
        self.assertEqual(resolved['ks_count'], 2)
        execution_result = {
            'ok': True,
            'success_count': 3,
            'target_count': 3,
            'channels': ['cocos', 'ks'],
            'batch_results': [
                {'ok': True, 'target': {'id': 'client-vip-1'}},
                *[
                    {'ok': True, 'target': {'cache_id': item['cache_id']}}
                    for item in workflow['runtime']['ks_targets']
                ],
            ],
        }
        with mock.patch.object(server, 'execute_gm_commands', return_value=execution_result) as execute_gm, \
                mock.patch.object(server, 'save_kongming_workflow', side_effect=lambda _base, value: value):
            result = server._workflow_execute_account_command(workflow)

        call = execute_gm.call_args
        self.assertEqual(call.args[0], ['#setVipLevel 12'])
        self.assertEqual(len(call.kwargs['target_specs']), 1)
        self.assertEqual(len(call.kwargs['ks_targets']), 2)
        self.assertEqual(result['success_count'], 3)


if __name__ == '__main__':
    unittest.main()
