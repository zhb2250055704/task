import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import server


class GitBranchOperationsTest(unittest.TestCase):
    repo_id = 'branch-test'

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='gm-tool-git-')
        self.remote = os.path.join(self.temp_dir, 'remote.git')
        self.seed = os.path.join(self.temp_dir, 'seed')
        self.work = os.path.join(self.temp_dir, 'work')

        self.git('init', '--bare', self.remote)
        self.git('init', self.seed)
        self.git('-C', self.seed, 'config', 'user.name', 'GM Tool Test')
        self.git('-C', self.seed, 'config', 'user.email', 'gm-tool@example.invalid')
        Path(self.seed, 'README.md').write_text('main\n', encoding='utf-8')
        Path(self.seed, 'tools').mkdir()
        Path(self.seed, 'tools', '.keep').write_text('', encoding='utf-8')
        self.git('-C', self.seed, 'add', 'README.md', 'tools/.keep')
        self.git('-C', self.seed, 'commit', '-m', 'initial')
        self.git('-C', self.seed, 'branch', '-M', 'main')
        self.git('-C', self.seed, 'remote', 'add', 'origin', self.remote)
        self.git('-C', self.seed, 'push', '-u', 'origin', 'main')

        self.git('-C', self.seed, 'switch', '-c', 'feature/source')
        Path(self.seed, 'feature.txt').write_text('remote branch\n', encoding='utf-8')
        self.git('-C', self.seed, 'add', 'feature.txt')
        self.git('-C', self.seed, 'commit', '-m', 'feature')
        self.git('-C', self.seed, 'push', '-u', 'origin', 'feature/source')
        self.git('-C', self.remote, 'symbolic-ref', 'HEAD', 'refs/heads/main')
        self.git('clone', self.remote, self.work)

        self.previous_repo = server.GIT_REPOS.get(self.repo_id)
        self.previous_tool_dir = server.TOOL_DIR
        server.GIT_REPOS[self.repo_id] = {'label': '分支测试', 'path': self.work}

    def tearDown(self):
        if self.previous_repo is None:
            server.GIT_REPOS.pop(self.repo_id, None)
        else:
            server.GIT_REPOS[self.repo_id] = self.previous_repo
        server.TOOL_DIR = self.previous_tool_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def git(*args):
        proc = subprocess.run(
            [server.git_executable(), *args],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        if proc.returncode != 0:
            raise AssertionError((proc.stdout + '\n' + proc.stderr).strip())
        return proc.stdout.strip()

    def test_status_lists_local_and_remote_branches(self):
        status = server.git_repo_status(self.repo_id, fetch_remote=True)

        self.assertTrue(status['ok'])
        self.assertEqual(status['current_branch'], 'main')
        self.assertIn('main', {item['name'] for item in status['local_branches']})
        self.assertIn('origin/feature/source', {item['name'] for item in status['remote_branches']})

    def test_remote_only_branch_creates_tracking_branch(self):
        server.git_repo_status(self.repo_id, fetch_remote=True)
        result = server.git_checkout_branch(self.repo_id, 'origin/feature/source', 'remote')

        self.assertTrue(result['ok'], result.get('msg'))
        self.assertTrue(result['created_tracking_branch'])
        self.assertEqual(result['current_branch'], 'feature/source')
        upstream = self.git('-C', self.work, 'rev-parse', '--abbrev-ref', '@{u}')
        self.assertEqual(upstream, 'origin/feature/source')

    def test_existing_local_branch_switches_directly(self):
        self.git('-C', self.work, 'switch', '-c', 'local/ready')
        self.git('-C', self.work, 'switch', 'main')

        result = server.git_checkout_branch(self.repo_id, 'local/ready', 'local')

        self.assertTrue(result['ok'], result.get('msg'))
        self.assertFalse(result['created_tracking_branch'])
        self.assertEqual(result['current_branch'], 'local/ready')

    def test_dirty_worktree_is_discarded_before_branch_switch(self):
        server.git_repo_status(self.repo_id, fetch_remote=True)
        Path(self.work, 'README.md').write_text('qa local edit\n', encoding='utf-8')
        Path(self.work, 'local-only.txt').write_text('do not move\n', encoding='utf-8')

        result = server.git_checkout_branch(self.repo_id, 'origin/feature/source', 'remote')

        self.assertTrue(result['ok'], result.get('msg'))
        self.assertEqual(result['discard']['count'], 2)
        self.assertEqual(self.git('-C', self.work, 'branch', '--show-current'), 'feature/source')
        self.assertEqual(Path(self.work, 'README.md').read_text(encoding='utf-8'), 'main\n')
        self.assertFalse(Path(self.work, 'local-only.txt').exists())

    def test_discard_preserves_gm_tool_directory(self):
        tool_dir = Path(self.work, 'tools', 'gm-command-tool')
        tool_dir.mkdir(parents=True)
        protected_file = tool_dir / 'index.html'
        protected_file.write_text('keep tool\n', encoding='utf-8')
        qa_file = Path(self.work, 'qa-local-only.txt')
        qa_file.write_text('discard me\n', encoding='utf-8')
        server.TOOL_DIR = str(tool_dir)

        result = server.git_discard_worktree_changes(server.GIT_REPOS[self.repo_id], self.repo_id)
        status = server.git_repo_status(self.repo_id, fetch_remote=False)

        self.assertTrue(result['ok'], result.get('output'))
        self.assertEqual(result['count'], 1)
        self.assertGreaterEqual(result['protected_count'], 1)
        self.assertTrue(protected_file.exists())
        self.assertFalse(qa_file.exists())
        self.assertFalse(status['dirty'])
        self.assertEqual(status['switch_blocked_reason'], '')

    def test_fetch_returns_refreshed_status(self):
        result = server.git_fetch_repo_result(self.repo_id)

        self.assertTrue(result['ok'], result.get('msg'))
        self.assertTrue(result['status']['branch_list_ok'])
        self.assertIn(
            'origin/feature/source',
            {item['name'] for item in result['status']['remote_branches']},
        )

    def test_status_job_refreshes_upstream_and_reaches_completion(self):
        self.git('-C', self.seed, 'switch', 'main')
        Path(self.seed, 'status-job.txt').write_text('remote status\n', encoding='utf-8')
        self.git('-C', self.seed, 'add', 'status-job.txt')
        self.git('-C', self.seed, 'commit', '-m', 'status job update')
        self.git('-C', self.seed, 'push', 'origin', 'main')

        job_id = server.start_git_status_job([self.repo_id])
        deadline = time.time() + 15
        job = server.git_job_snapshot(job_id)
        while job and job.get('state') not in ('done', 'failed') and time.time() < deadline:
            time.sleep(0.05)
            job = server.git_job_snapshot(job_id)

        self.assertIsNotNone(job)
        self.assertEqual(job['state'], 'done', job.get('detail'))
        self.assertEqual(job['percent'], 100)
        self.assertTrue(job['result']['remote_refresh_ok'])
        self.assertEqual(job['result']['items'][0]['remote_count'], 1)

    def test_pull_discards_local_changes_without_creating_stash(self):
        self.git('-C', self.seed, 'switch', 'main')
        Path(self.seed, 'README.md').write_text('remote update\n', encoding='utf-8')
        self.git('-C', self.seed, 'add', 'README.md')
        self.git('-C', self.seed, 'commit', '-m', 'remote update')
        self.git('-C', self.seed, 'push', 'origin', 'main')
        Path(self.work, 'README.md').write_text('qa local edit\n', encoding='utf-8')
        Path(self.work, 'qa-local-only.txt').write_text('discard me\n', encoding='utf-8')

        result = server.git_pull_repo_result(self.repo_id)

        self.assertTrue(result['ok'], result.get('output'))
        self.assertEqual(result['discard']['count'], 2)
        self.assertEqual(Path(self.work, 'README.md').read_text(encoding='utf-8'), 'remote update\n')
        self.assertFalse(Path(self.work, 'qa-local-only.txt').exists())
        self.assertEqual(self.git('-C', self.work, 'stash', 'list'), '')

    def test_pull_job_is_rejected_during_manual_git_operation(self):
        server._git_operation_lock.acquire()
        try:
            with self.assertRaises(BlockingIOError):
                server.start_git_pull_job([self.repo_id])
        finally:
            server._git_operation_lock.release()


if __name__ == '__main__':
    unittest.main()
