import json
import os
import unittest
import urllib.error
from unittest import mock

import server


class KsTokenBridgeTest(unittest.TestCase):
    def test_extension_manifest_limits_token_bridge_origins(self):
        manifest_path = os.path.join(server.KS_TOKEN_BRIDGE_DIR, 'manifest.json')
        with open(manifest_path, 'r', encoding='utf-8') as handle:
            manifest = json.load(handle)

        self.assertEqual(manifest['manifest_version'], 3)
        self.assertEqual(manifest['version'], '1.1.0')
        self.assertIn('https://zxty.tuyoo.com/keystone/*', manifest['host_permissions'])
        self.assertIn('http://localhost:9092/*', manifest['host_permissions'])
        self.assertNotIn('<all_urls>', manifest['host_permissions'])

    def test_extension_files_are_complete(self):
        for filename in ('manifest.json', 'background.js', 'content.js', 'README.md'):
            self.assertTrue(os.path.isfile(os.path.join(server.KS_TOKEN_BRIDGE_DIR, filename)))

    def test_command_page_retries_bridge_when_saved_token_is_missing_or_expired(self):
        index_path = os.path.join(server.TOOL_DIR, 'index.html')
        with open(index_path, 'r', encoding='utf-8') as handle:
            source = handle.read()

        self.assertIn("if (!alreadySynced || !data.configured || data.expired)", source)
        self.assertNotIn("const bridgeAttempted = sessionStorage.getItem('gm_ks_token_bridge_attempted')", source)

    def test_ks_request_retries_transient_file_connection_errors(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"results": []}'
        response.headers = {'Content-Type': 'application/json'}
        transient = urllib.error.URLError(FileNotFoundError(2, 'No such file or directory'))
        with mock.patch.object(
            server.urllib.request,
            'urlopen',
            side_effect=[transient, transient, response],
        ) as urlopen, mock.patch.object(server.time, 'sleep') as sleep:
            result = server.ks_request_json(
                'https://zxty.tuyoo.com', 'token', '/idp/apk/projects/all'
            )

        self.assertEqual(result, {'results': []})
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(sleep.call_count, 2)


if __name__ == '__main__':
    unittest.main()
