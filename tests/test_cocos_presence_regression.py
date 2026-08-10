import threading
import unittest

import server


class CocosPresenceRegressionTest(unittest.TestCase):
    def test_identity_hello_gets_bridge_connection_id(self):
        connection = object.__new__(server.CocosBridgeConnection)
        connection.connection_id = 'direct:5101:1'
        connection.address = ('127.0.0.1', 5101)
        connection.info_lock = threading.Lock()
        connection.target_info = {}
        connection.target_info_updated_at = 0

        self.assertTrue(connection.set_target_info({
            'environmentUrl': 'https://login-test-202.example.com',
            'roleId': 10100000240322,
            'serverId': 101,
            'ready': True,
        }))

        target = connection.target_snapshot()
        self.assertEqual(target['client_id'], 'direct:5101:1')
        self.assertTrue(target['dispatchable'])
        self.assertEqual(target['role_id'], '10100000240322')
        self.assertEqual(target['server_id'], '101')

    def test_role_match_accepts_same_environment_and_role(self):
        account = {
            'account_name': '101.A.account.721495',
            'role_id': '10100000240322',
            'server_id': '101',
        }
        target = {
            'environment_url': 'https://login-test-202-26a3a3c6-sanguo2.example.com',
            'role_id': '10100000240322',
            'server_id': '101',
        }

        account['environment_url'] = target['environment_url']
        self.assertEqual(server._ks_display_account_match(account, target), 10)

    def test_role_match_rejects_wrong_server_even_when_role_matches(self):
        account = {
            'environment_url': 'https://login-test-202-26a3a3c6-sanguo2.example.com',
            'role_id': '10100000240322',
            'server_id': '101',
        }
        target = {
            'environment_url': 'https://login-test-202-26a3a3c6-sanguo2.example.com',
            'role_id': '10100000240322',
            'server_id': '102',
        }

        self.assertEqual(server._ks_display_account_match(account, target), -1)


if __name__ == '__main__':
    unittest.main()
