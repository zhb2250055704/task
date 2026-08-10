import unittest

import server


class HanZhongPersonalScoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = server.parse_hanzhong_personal_scores()
        cls.by_id = {item['id']: item for item in cls.items}

    def test_reads_all_personal_score_rules(self):
        self.assertEqual(len(self.items), 40)
        self.assertEqual({item['type'] for item in self.items}, set(range(1, 13)))

    def test_maps_requested_excel_columns(self):
        first = self.by_id[1]
        self.assertEqual(first['parameter'], 1)
        self.assertEqual(first['unit_score'], 40000)
        self.assertEqual(first['parameter_note'], '参数1代表山腰')
        self.assertEqual(first['description'], '攻占1个山腰空地')

    def test_level_score_curve_uses_parameter_and_score(self):
        enemy_level_15 = next(
            item for item in self.items if item['type'] == 9 and item['parameter'] == 15
        )
        own_level_15 = next(
            item for item in self.items if item['type'] == 10 and item['parameter'] == 15
        )
        self.assertEqual(enemy_level_15['unit_score'], 20)
        self.assertEqual(own_level_15['unit_score'], 40)
        self.assertIn('15级', enemy_level_15['description'])

    def test_multiple_completed_tasks_sum_from_unit_scores(self):
        completed = {
            1: 2,
            23: 10,
            39: 100,
            40: 3,
        }
        total = sum(self.by_id[item_id]['unit_score'] * quantity for item_id, quantity in completed.items())
        self.assertEqual(total, 635200)


if __name__ == '__main__':
    unittest.main()
