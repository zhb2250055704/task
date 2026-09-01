import tempfile
import unittest
from unittest import mock

import server
from kongming_tasks import create_task, normalize_task_plan, save_task


class KongmingTaskServiceTests(unittest.TestCase):
    def test_generic_ks_query_matches_catalog_environment(self):
        environment = {
            'key': 'env-141', 'name': '测试环境 205',
            'login_url': 'https://login-test-205.example.com',
        }
        self.assertTrue(server._task_environment_matches(
            environment, {'environment_keys': [], 'environment_query': 'KS 环境'}
        ))

    def test_empty_target_scope_never_selects_every_account(self):
        with mock.patch.object(server, 'ks_catalog_status') as catalog:
            catalog.return_value = {'catalog': {'environments': [{
                'key': 'env-1',
                'accounts': [{'id': 'client-1', 'dispatchable': True}],
            }]}}
            self.assertEqual(server._resolve_kongming_task_targets({}), [])

    def test_generic_ks_scope_rejects_multiple_environments(self):
        with self.assertRaises(RuntimeError):
            server._validate_kongming_task_target_scope(
                {'environment_query': 'KS 环境', 'environment_keys': []},
                [{'environment_key': 'env-1'}, {'environment_key': 'env-2'}],
            )

    def test_prepare_plan_resolves_registered_command_and_targets(self):
        plan = normalize_task_plan({
            'kind': 'task',
            'steps': [{
                'action': 'execute_gm',
                'title': '成为天子',
                'params': {'command_query': '成为王盟(S1)/天子'},
                'target': {'environment_keys': ['env-1'], 'server_ids': ['141']},
            }],
        })
        command = {
            'id': 'king', 'name': '成为王盟(S1)/天子',
            'command': '#setKingAppointBegin', 'params': '',
        }
        target = {
            'id': 'client-1', 'environment_key': 'env-1', 'environment_name': '测试环境',
            'account_label': '盟主', 'server_id': '141', 'role_id': '141001',
            'dispatchable': True,
        }
        with mock.patch.object(server, 'load_data', return_value=[command]), \
                mock.patch.object(server, 'load_scripts', return_value=[]), \
                mock.patch.object(server, '_resolve_kongming_task_targets', return_value=[target]):
            prepared = server._prepare_kongming_task_plan(plan)

        self.assertFalse(prepared['blockers'])
        self.assertEqual(prepared['steps'][0]['params']['command_id'], 'king')
        self.assertEqual(prepared['steps'][0]['params']['resolved_command'], '#setKingAppointBegin')
        self.assertEqual(prepared['steps'][0]['target_count'], 1)

    def test_worker_stops_after_failure_and_skips_remaining_steps(self):
        plan = normalize_task_plan({
            'kind': 'task',
            'steps': [
                {'action': 'sync_accounts', 'title': '同步'},
                {'action': 'git_pull', 'title': '拉取', 'params': {'repo_ids': ['client']}},
                {'action': 'wait_for_login', 'title': '等待登录'},
            ],
        })
        task = create_task('owner', '依次执行', plan)
        calls = []

        def execute(step):
            calls.append(step['title'])
            if step['title'] == '拉取':
                raise RuntimeError('模拟失败')
            return {'message': '完成'}

        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(server, 'KONGMING_TASK_DIR', temp_dir), \
                mock.patch.object(server, '_execute_kongming_task_step', side_effect=execute):
            save_task(temp_dir, task)
            server._run_kongming_task_worker(task)

        self.assertEqual(calls, ['同步', '拉取'])
        self.assertEqual(task['status'], 'failed')
        self.assertEqual([step['status'] for step in task['steps']], ['succeeded', 'failed', 'skipped'])

    def test_start_rejects_blocked_task(self):
        plan = normalize_task_plan({
            'kind': 'task',
            'steps': [{'action': 'unsupported_action', 'title': '未知动作'}],
        })
        task = create_task('owner', '执行未知动作', plan)
        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(server, 'KONGMING_TASK_DIR', temp_dir):
            save_task(temp_dir, task)
            with self.assertRaises(server.KongmingTaskBlocked):
                server.start_kongming_task('owner', task['id'], 'admin')

    def test_draft_command_can_be_edited_and_persisted(self):
        plan = normalize_task_plan({
            'kind': 'task',
            'steps': [{
                'id': 'money-step', 'action': 'execute_gm', 'title': '发放元宝',
                'params': {'command_id': 'money', 'command_query': '添加货币', 'command_args': '43 10'},
                'target': {'server_ids': ['101']},
            }],
        })
        task = create_task('owner', '发放元宝', plan)
        task['steps'][0]['params']['resolved_command'] = '#money 43 10'
        command = {
            'id': 'money', 'name': '添加货币', 'command': '#money',
            'params': 'type=货币类型 amount=数量',
        }
        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(server, 'KONGMING_TASK_DIR', temp_dir), \
                mock.patch.object(server, 'load_data', return_value=[command]):
            save_task(temp_dir, task)
            updated = server.update_kongming_task_command(
                'owner', task['id'], 'money-step', '#money 43 100000000', 'admin'
            )
            persisted = server.load_task(temp_dir, 'owner', task['id'])

        self.assertEqual(updated['steps'][0]['params']['resolved_command'], '#money 43 100000000')
        self.assertEqual(persisted['steps'][0]['params']['command_args'], '43 100000000')
        self.assertEqual(persisted['edits'][0]['operator'], 'admin')

    def test_task_edit_rejects_unregistered_or_multiline_command(self):
        plan = normalize_task_plan({
            'kind': 'task',
            'steps': [{'id': 'gm', 'action': 'execute_gm', 'title': 'GM'}],
        })
        task = create_task('owner', 'GM', plan)
        command = {'id': 'money', 'name': '添加货币', 'command': '#money', 'params': 'type amount'}
        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(server, 'KONGMING_TASK_DIR', temp_dir), \
                mock.patch.object(server, 'load_data', return_value=[command]):
            save_task(temp_dir, task)
            with self.assertRaisesRegex(ValueError, '未在'):
                server.update_kongming_task_command('owner', task['id'], 'gm', '#unknown 1')
            with self.assertRaisesRegex(ValueError, '一行'):
                server.update_kongming_task_command('owner', task['id'], 'gm', '#money 43 1\n#money 43 2')


if __name__ == '__main__':
    unittest.main()
