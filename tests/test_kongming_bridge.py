import os
import tempfile
import unittest

from kongming_bridge import (
    _create_directory_link,
    _is_directory_link,
    ensure_agents_skills_link,
    get_kongming_bridge_status,
    load_kongming_source,
    save_kongming_source,
)


def create_skill(root, name):
    skill_dir = os.path.join(root, name)
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, 'SKILL.md'), 'w', encoding='utf-8') as target:
        target.write(f'# {name}\n')
    return skill_dir


class KongmingBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = os.path.join(self.temp_dir.name, 'workspace')
        self.source = os.path.join(self.workspace, '.claude', 'skills')
        os.makedirs(self.workspace)
        os.makedirs(self.source)
        create_skill(self.source, 'company-qa')
        create_skill(self.source, 'game-review')

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_creates_workspace_link_and_is_idempotent(self):
        first = ensure_agents_skills_link(self.workspace, self.source)
        discovery = os.path.join(self.workspace, '.agents', 'skills')

        self.assertTrue(first['ready'])
        self.assertEqual(first['state'], 'linked')
        self.assertTrue(first['changed'])
        self.assertTrue(_is_directory_link(discovery))
        self.assertIn(first['link_kind'], ('symlink', 'junction'))
        if os.path.islink(discovery):
            self.assertFalse(os.path.isabs(os.readlink(discovery)))

        second = ensure_agents_skills_link(self.workspace, self.source)
        self.assertTrue(second['ready'])
        self.assertFalse(second['changed'])

    def test_merges_into_real_directory_without_overwriting_names(self):
        discovery = os.path.join(self.workspace, '.agents', 'skills')
        os.makedirs(os.path.join(discovery, 'company-qa'))

        result = ensure_agents_skills_link(self.workspace, self.source)

        self.assertTrue(result['ready'])
        self.assertEqual(result['state'], 'merged')
        self.assertEqual(result['link_kind'], 'merged')
        self.assertIn('company-qa', result['skipped'])
        self.assertIn('game-review', result['created'])
        self.assertFalse(os.path.islink(os.path.join(discovery, 'company-qa')))
        self.assertTrue(_is_directory_link(os.path.join(discovery, 'game-review')))

    def test_reports_missing_source_without_creating_agents_directory(self):
        missing_source = os.path.join(self.workspace, 'missing-skills')

        result = ensure_agents_skills_link(self.workspace, missing_source)

        self.assertFalse(result['ready'])
        self.assertEqual(result['state'], 'source_missing')
        self.assertFalse(os.path.exists(os.path.join(self.workspace, '.agents')))

    def test_does_not_replace_link_that_points_elsewhere(self):
        other_source = os.path.join(self.temp_dir.name, 'other-skills')
        os.makedirs(other_source)
        agents_dir = os.path.join(self.workspace, '.agents')
        os.makedirs(agents_dir)
        _create_directory_link(os.path.join(agents_dir, 'skills'), other_source)

        result = ensure_agents_skills_link(self.workspace, self.source)

        self.assertFalse(result['ready'])
        self.assertEqual(result['state'], 'conflict')
        resolved = os.path.realpath(os.path.join(agents_dir, 'skills'))
        self.assertEqual(os.path.normcase(resolved), os.path.normcase(os.path.realpath(other_source)))

    def test_saves_and_reloads_source_configuration(self):
        config_file = os.path.join(self.temp_dir.name, 'runtime', 'config.json')
        saved = save_kongming_source(config_file, self.source, self.workspace)
        loaded, origin = load_kongming_source(self.workspace, config_file, environ={})

        self.assertEqual(saved, loaded)
        self.assertEqual(origin, 'saved')

    def test_status_only_counts_directories_with_skill_manifest(self):
        os.makedirs(os.path.join(self.source, 'notes'))

        status = get_kongming_bridge_status(self.workspace, self.source)

        self.assertEqual(status['skill_count'], 2)
        self.assertEqual([item['name'] for item in status['skills']], ['company-qa', 'game-review'])


if __name__ == '__main__':
    unittest.main()
