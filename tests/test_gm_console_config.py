import os
import tempfile
import unittest
from unittest import mock

import server


class GmConsoleConfigTests(unittest.TestCase):
    def test_credentials_persist_only_in_local_config(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(
                    server, 'GM_CONSOLE_CONFIG_FILE', os.path.join(temp_dir, 'gm_console_config.json')
                ), \
                mock.patch.dict(os.environ, {
                    'GM_CONSOLE_TOKEN': '',
                    'GM_CONSOLE_COOKIE': '',
                    'GM_CONSOLE_USERNAME': '',
                    'GM_CONSOLE_PASSWORD': '',
                }, clear=False):
            server.save_gm_console_config(
                username='admin', password='local-secret', token='token', cookie='cookie'
            )
            config = server.load_gm_console_config()

        self.assertEqual(config['username'], 'admin')
        self.assertEqual(config['password'], 'local-secret')
        self.assertEqual(config['token'], 'token')
        self.assertEqual(config['cookie'], 'cookie')

    def test_auto_login_uses_local_credentials(self):
        with mock.patch.object(server, 'load_gm_console_config', return_value={
            'username': 'admin',
            'password': 'local-secret',
        }), mock.patch.object(
            server, 'gm_console_login', return_value={'ok': True}
        ) as login:
            result = server.gm_console_auto_login('env-1')

        self.assertTrue(result['ok'])
        login.assert_called_once_with('env-1', 'admin', 'local-secret')


if __name__ == '__main__':
    unittest.main()
