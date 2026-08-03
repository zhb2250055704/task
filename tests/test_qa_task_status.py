import unittest

from qa_local_engine import get_local_qa_task_status
from server import qa_test_design_status, set_qa_codex_task_status


class QaTaskStatusTests(unittest.TestCase):
    def tearDown(self):
        set_qa_codex_task_status(False)

    def test_status_exposes_active_codex_generation(self):
        set_qa_codex_task_status(True, 'points', '汉中争锋')
        task = qa_test_design_status()['providers']['codex']['task']
        self.assertTrue(task['running'])
        self.assertEqual(task['mode'], 'points')
        self.assertEqual(task['title'], '汉中争锋')
        self.assertEqual(task['engine'], 'Codex')
        self.assertGreaterEqual(task['elapsed_ms'], 0)

    def test_local_status_is_available_while_idle(self):
        task = get_local_qa_task_status()
        self.assertIn('running', task)
        self.assertIn('mode', task)
        self.assertEqual(task['engine'], '本地测试引擎')


if __name__ == '__main__':
    unittest.main()
