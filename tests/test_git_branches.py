import os
import shutil
import subprocess
import tempfile
import time
import unittest
import zipfile
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

    def test_unified_checkout_switches_client_and_excel_together(self):
        excel_work = os.path.join(self.temp_dir, 'excel-work')
        self.git('clone', self.remote, excel_work)
        previous_client = server.GIT_REPOS.get('client')
        previous_excel = server.GIT_REPOS.get('excel')
        server.GIT_REPOS['client'] = {'label': '客户端', 'path': self.work}
        server.GIT_REPOS['excel'] = {'label': '配置表', 'path': excel_work}
        try:
            result = server.git_checkout_unified_branch([
                {'repo': 'client', 'branch': 'origin/feature/source', 'source': 'remote'},
                {'repo': 'excel', 'branch': 'origin/feature/source', 'source': 'remote'},
            ])

            self.assertTrue(result['ok'], result.get('msg'))
            self.assertEqual([item['id'] for item in result['items']], ['client', 'excel'])
            self.assertEqual(self.git('-C', self.work, 'branch', '--show-current'), 'feature/source')
            self.assertEqual(self.git('-C', excel_work, 'branch', '--show-current'), 'feature/source')
        finally:
            if previous_client is None:
                server.GIT_REPOS.pop('client', None)
            else:
                server.GIT_REPOS['client'] = previous_client
            if previous_excel is None:
                server.GIT_REPOS.pop('excel', None)
            else:
                server.GIT_REPOS['excel'] = previous_excel


class ConfigCompareTest(unittest.TestCase):
    repo_id = 'config-compare-test'

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='gm-tool-config-compare-')
        self.work = os.path.join(self.temp_dir, 'excel')
        self.git('init', self.work)
        self.git('-C', self.work, 'config', 'user.name', 'GM Tool Test')
        self.git('-C', self.work, 'config', 'user.email', 'gm-tool@example.invalid')
        self.git('-C', self.work, 'branch', '-M', 'main')
        self.previous_repo = server.GIT_REPOS.get(self.repo_id)
        server.GIT_REPOS[self.repo_id] = {'label': '配置表测试', 'path': self.work}

    def tearDown(self):
        if self.previous_repo is None:
            server.GIT_REPOS.pop(self.repo_id, None)
        else:
            server.GIT_REPOS[self.repo_id] = self.previous_repo
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

    @staticmethod
    def write_xlsx(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            '<row r="1"><c r="A1" t="inlineStr"><is><t>id</t></is></c><c r="B1" t="inlineStr"><is><t>name</t></is></c></row>',
            f'<row r="2"><c r="A2"><v>1</v></c><c r="B2" t="inlineStr"><is><t>{value}</t></is></c></row>',
        ]
        files = {
            '[Content_Types].xml': (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                '</Types>'
            ),
            'xl/workbook.xml': (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>'
            ),
            'xl/_rels/workbook.xml.rels': (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                '</Relationships>'
            ),
            'xl/worksheets/sheet1.xml': (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' +
                ''.join(rows) + '</sheetData></worksheet>'
            ),
        }
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, content)

    def commit_demo_version(self, value, subject):
        path = Path(self.work, 'csv', 'common', 'Demo.xlsx')
        self.write_xlsx(path, value)
        self.git('-C', self.work, 'add', 'csv/common/Demo.xlsx')
        self.git('-C', self.work, 'commit', '-m', subject)

    def test_lists_tables_and_compares_three_previous_versions(self):
        for index in range(4):
            self.commit_demo_version(f'v{index}', f'demo version {index}')
        Path(self.work, 'README.md').write_text('unrelated commit\n', encoding='utf-8')
        self.git('-C', self.work, 'add', 'README.md')
        self.git('-C', self.work, 'commit', '-m', 'unrelated update')

        result = server.git_config_compare_tables(self.repo_id)
        self.assertTrue(result['ok'], result.get('msg'))
        self.assertEqual(result['branch'], 'main')
        self.assertIn('csv/common/Demo.xlsx', {item['path'] for item in result['items']})

        comparison = server.git_config_compare_file('csv/common/Demo.xlsx', self.repo_id)
        self.assertTrue(comparison['ok'], comparison.get('msg'))
        self.assertEqual(comparison['history_count'], 3)
        self.assertEqual([item['rank'] for item in comparison['comparisons']], [1, 2, 3])
        first = comparison['comparisons'][0]
        self.assertEqual(first['summary']['changed_cells'], 1)
        self.assertEqual(first['summary']['changed_fields'][0]['column'], 'B')
        self.assertEqual(first['sheets'][0]['name'], 'Data')
        self.assertEqual(first['sheets'][0]['rows'][0]['cells'][1]['after'], 'v3')

    def test_history_shortage_and_path_validation_are_explicit(self):
        one = Path(self.work, 'csv', 'common', 'One.xlsx')
        self.write_xlsx(one, 'one-only')
        self.git('-C', self.work, 'add', 'csv/common/One.xlsx')
        self.git('-C', self.work, 'commit', '-m', 'one table')

        comparison = server.git_config_compare_file('csv/common/One.xlsx', self.repo_id)
        self.assertTrue(comparison['ok'], comparison.get('msg'))
        self.assertEqual(comparison['history_count'], 0)
        self.assertEqual(comparison['comparisons'], [])

        for path in ('../One.xlsx', 'csv/other/One.xlsx', 'csv/common/One.csv'):
            rejected = server.git_config_compare_file(path, self.repo_id)
            self.assertFalse(rejected['ok'])
            self.assertEqual(rejected['code'], 'invalid_path')


if __name__ == '__main__':
    unittest.main()
