import unittest

import server


class GitDetailPreviewTests(unittest.TestCase):
    def test_large_diff_is_limited_to_a_line_boundary(self):
        diff = '\n'.join(f'+changed line {index}' for index in range(10000))

        preview, total_chars, truncated = server.git_detail_diff_preview(diff, limit=200)

        self.assertEqual(total_chars, len(diff))
        self.assertTrue(truncated)
        self.assertLess(len(preview), len(diff))
        self.assertIn('[原始 Diff 共 ', preview)
        self.assertNotIn('changed line 9999', preview)

    def test_large_excel_sheet_obeys_cell_budget_and_value_limit(self):
        before = {'name': 'Dropgroup', 'cells': {}}
        after = {'name': 'Dropgroup', 'cells': {}}
        for row in range(1, 21):
            for column in range(1, 11):
                before['cells'][(row, column)] = 'old value ' + ('x' * 80)
                after['cells'][(row, column)] = 'new value ' + ('y' * 80)

        sheets = server.compare_xlsx_sheets(
            [before],
            [after],
            max_rows=80,
            max_cols=120,
            max_table_cells=24,
            cell_value_limit=20,
        )

        self.assertEqual(len(sheets), 1)
        sheet = sheets[0]
        self.assertLessEqual(sheet['shown_cells'], 24)
        self.assertEqual(sheet['shown_cells'], 20)
        self.assertEqual(sheet['shown_rows'], 2)
        self.assertTrue(sheet['truncated'])
        self.assertTrue(sheet['cell_value_truncated'])
        self.assertTrue(sheet['rows'][0]['cells'][0]['value_truncated'])
        self.assertLess(len(sheet['rows'][0]['cells'][0]['after']), 100)


if __name__ == '__main__':
    unittest.main()
