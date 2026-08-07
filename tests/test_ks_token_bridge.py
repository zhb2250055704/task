import json
import os
import unittest

import server


class KsTokenBridgeTest(unittest.TestCase):
    def test_extension_manifest_limits_token_bridge_origins(self):
        manifest_path = os.path.join(server.KS_TOKEN_BRIDGE_DIR, 'manifest.json')
        with open(manifest_path, 'r', encoding='utf-8') as handle:
            manifest = json.load(handle)

        self.assertEqual(manifest['manifest_version'], 3)
        self.assertIn('https://zxty.tuyoo.com/keystone/*', manifest['host_permissions'])
        self.assertIn('http://localhost:9092/*', manifest['host_permissions'])
        self.assertNotIn('<all_urls>', manifest['host_permissions'])

    def test_extension_files_are_complete(self):
        for filename in ('manifest.json', 'background.js', 'content.js', 'README.md'):
            self.assertTrue(os.path.isfile(os.path.join(server.KS_TOKEN_BRIDGE_DIR, filename)))


if __name__ == '__main__':
    unittest.main()
