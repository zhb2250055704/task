import json
import os
import sqlite3
import tempfile
import time
import unittest

from kongming_index import (
    get_kongming_index_status,
    search_kongming_index,
    sync_kongming_index,
)


def write_table(path, name, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as target:
        json.dump({
            'sheets': [{
                'name': name,
                'rows': [
                    {'cells': {'A': 'id', 'B': 'name'}},
                    {'cells': {'A': '1', 'B': value}},
                ],
            }],
        }, target, ensure_ascii=False)


class KongmingIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.json_root = os.path.join(self.temp_dir.name, 'json')
        self.index_path = os.path.join(self.temp_dir.name, 'runtime', 'search-index.sqlite3')
        self.antique_path = os.path.join(self.json_root, 'csv', 'common', 'COA_Antique.json')
        self.activity_path = os.path.join(self.json_root, 'csv', 'common', 'COA_Activity.json')
        write_table(self.antique_path, 'Antique', '鉴宝活动')
        write_table(self.activity_path, 'Activity', '九州风采')

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_initial_index_and_search(self):
        result = sync_kongming_index(self.json_root, self.index_path)
        matches, status = search_kongming_index(
            self.index_path, self.json_root, ['鉴宝'], limit=20
        )

        self.assertTrue(result['ready'])
        self.assertEqual(result['file_count'], 2)
        self.assertEqual(result['changed_count'], 2)
        self.assertTrue(status['ready'])
        self.assertIn(os.path.abspath(self.antique_path), matches)
        self.assertNotIn(os.path.abspath(self.activity_path), matches)

        connection = sqlite3.connect(self.index_path)
        digest = connection.execute(
            'SELECT sha256 FROM files WHERE path=?',
            ('csv/common/COA_Antique.json',),
        ).fetchone()[0]
        connection.close()
        self.assertEqual(len(digest), 64)

    def test_incrementally_updates_added_changed_and_removed_files(self):
        first = sync_kongming_index(self.json_root, self.index_path)
        time.sleep(0.01)
        write_table(self.antique_path, 'Antique', '奇兵突袭')
        os.remove(self.activity_path)
        new_path = os.path.join(self.json_root, 'csv', 'common', 'COA_NewEvent.json')
        write_table(new_path, 'NewEvent', '群雄争霸')

        second = sync_kongming_index(self.json_root, self.index_path)
        old_matches, _status = search_kongming_index(
            self.index_path, self.json_root, ['鉴宝'], limit=20
        )
        new_matches, _status = search_kongming_index(
            self.index_path, self.json_root, ['奇兵突袭'], limit=20
        )

        self.assertEqual(first['generation'] + 1, second['generation'])
        self.assertEqual(second['changed_count'], 2)
        self.assertEqual(second['removed_count'], 1)
        self.assertNotIn(os.path.abspath(self.antique_path), old_matches)
        self.assertIn(os.path.abspath(self.antique_path), new_matches)
        self.assertEqual(get_kongming_index_status(self.index_path)['file_count'], 2)

    def test_unchanged_sync_does_not_advance_generation(self):
        first = sync_kongming_index(self.json_root, self.index_path)
        second = sync_kongming_index(self.json_root, self.index_path)

        self.assertEqual(second['changed_count'], 0)
        self.assertEqual(second['removed_count'], 0)
        self.assertEqual(second['generation'], first['generation'])


if __name__ == '__main__':
    unittest.main()
