import tempfile
import unittest

from kongming_tasks import (
    build_task_planner_prompt,
    create_task,
    extract_task_plan_json,
    load_task,
    normalize_task_plan,
    public_task,
    save_task,
)


class KongmingTaskTests(unittest.TestCase):
    def test_extracts_fenced_json(self):
        value = extract_task_plan_json('结果如下\n```json\n{"kind":"chat"}\n```')
        self.assertEqual(value['kind'], 'chat')

    def test_normalizes_dynamic_steps_and_dependencies(self):
        plan = normalize_task_plan({
            'kind': 'task',
            'title': '同步后执行命令',
            'steps': [
                {'id': 'sync', 'action': 'sync_accounts', 'title': '同步账号'},
                {
                    'id': 'gm', 'action': 'execute_gm', 'title': '成为天子',
                    'params': {'command_id': 'imp_setkingappointbegin'},
                    'target': {'server_ids': ['165', '181'], 'channel': 'ks'},
                },
            ],
        })
        self.assertEqual(len(plan['steps']), 2)
        self.assertEqual(plan['steps'][1]['depends_on'], ['sync'])
        self.assertEqual(plan['steps'][1]['target']['server_ids'], ['165', '181'])

    def test_unknown_action_becomes_blocked_manual_step(self):
        plan = normalize_task_plan({
            'kind': 'task',
            'steps': [{'action': 'create_magic_account', 'title': '创建账号'}],
        })
        self.assertEqual(plan['steps'][0]['action'], 'manual')
        self.assertTrue(plan['blockers'])
        task = create_task('owner', '创建账号', plan)
        self.assertEqual(task['status'], 'blocked')

    def test_command_arguments_cannot_inject_extra_lines(self):
        plan = normalize_task_plan({
            'kind': 'task',
            'steps': [{
                'action': 'execute_gm',
                'params': {'command_id': 'money', 'command_args': '43 10\n#anotherCommand'},
                'target': {'all_accounts': True, 'channel': 'online'},
            }],
        })
        self.assertEqual(plan['steps'][0]['params']['command_args'], '43 10 #anotherCommand')

    def test_task_storage_is_owner_isolated(self):
        plan = normalize_task_plan({
            'kind': 'task',
            'steps': [{'action': 'sync_accounts', 'title': '同步账号'}],
        })
        task = create_task('owner-a', '同步', plan)
        with tempfile.TemporaryDirectory() as temp_dir:
            save_task(temp_dir, task)
            self.assertEqual(load_task(temp_dir, 'owner-a', task['id'])['id'], task['id'])
            self.assertIsNone(load_task(temp_dir, 'owner-b', task['id']))
        self.assertNotIn('owner_id', public_task(task))

    def test_prompt_allows_variable_steps_but_only_registered_actions(self):
        prompt = build_task_planner_prompt('完成这些操作', [], {'commands': []})
        self.assertIn('允许 1 到 60 步', prompt)
        self.assertIn('不得输出 shell', prompt)
        self.assertIn('wait_for_login', prompt)


if __name__ == '__main__':
    unittest.main()
