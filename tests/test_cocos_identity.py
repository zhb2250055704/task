import unittest

import server


class CocosIdentityTest(unittest.TestCase):
    def test_direct_connection_falls_back_to_existing_role_info_rpc(self):
        connection = object.__new__(server.CocosBridgeConnection)
        connection.connection_id = 'direct:5101'
        calls = []
        captured = {}

        def send_rpc(method, params):
            calls.append(method)
            if method != 'roleInfo':
                return {'ok': False, 'error': 'method not found'}
            return {
                'ok': True,
                'result': {
                    'ok': True,
                    'gameServer': 'https://login-test-201.example.com',
                    'roleId': 14100000240526,
                    'roleName': 'QA Role',
                    'serverId': 141,
                    'tokenEventActivityMetaId': '457002',
                },
            }

        connection.send_rpc = send_rpc
        connection.set_target_info = lambda info: captured.update(info)

        self.assertTrue(connection.refresh_target_info())
        self.assertEqual(calls, ['getGMContext', 'getGmTargetInfo', 'roleInfo'])
        self.assertEqual(captured['environmentUrl'], 'https://login-test-201.example.com')
        self.assertEqual(captured['roleId'], '14100000240526')
        self.assertEqual(captured['clientId'], 'direct:5101')
        self.assertEqual(captured['tokenEventActivityMetaId'], '457002')
        self.assertTrue(captured['ready'])

    def test_role_info_fallback_preserves_fish_activity_meta_id(self):
        connection = object.__new__(server.CocosBridgeConnection)
        connection.connection_id = 'direct:5101:fish'
        captured = {}

        def send_rpc(method, params):
            if method != 'roleInfo':
                return {'ok': False, 'error': 'method not found'}
            return {
                'ok': True,
                'result': {
                    'ok': True,
                    'gameServer': 'https://login-test-201.example.com',
                    'roleId': 14100000240526,
                    'roleName': 'QA Role',
                    'serverId': 141,
                    'fishActivityMetaId': '457001',
                    'tokenEventActivityMetaId': '457002',
                },
            }

        connection.send_rpc = send_rpc
        connection.set_target_info = lambda info: captured.update(info)

        self.assertTrue(connection.refresh_target_info())
        self.assertEqual(captured['fishActivityMetaId'], '457001')
        self.assertEqual(captured['tokenEventActivityMetaId'], '457002')

    def test_complete_proxy_context_is_dispatchable(self):
        target = server._cocos_proxy_target({
            'clientId': '5101-1',
            'connectedAt': 1000,
            'context': {
                'environmentUrl': 'https://login-test-201.example.com/',
                'accountId': '12345',
                'accountName': '141.A.account.462068',
                'roleId': '14100000240526',
                'roleName': 'QA Role',
                'serverId': '141',
                'ready': True,
            },
        }, 5101)

        self.assertTrue(target['dispatchable'])
        self.assertTrue(target['identity_complete'])
        self.assertEqual(target['role_name'], 'QA Role')
        self.assertEqual(target['environment_url'], 'https://login-test-201.example.com')

    def test_missing_client_identity_is_not_dispatchable(self):
        target = server._cocos_proxy_target({
            'clientId': '5101-2',
            'context': {},
        }, 5101)

        self.assertFalse(target['dispatchable'])
        self.assertFalse(target['identity_complete'])

    def test_role_identity_does_not_require_account_id(self):
        target = server._cocos_proxy_target({
            'clientId': '5101-3',
            'context': {
                'environmentUrl': 'https://login-test-201.example.com',
                'roleId': '14100000240526',
                'roleName': 'QA Role',
                'serverId': '141',
                'ready': True,
            },
        }, 5101)

        self.assertTrue(target['dispatchable'])
        self.assertEqual(target['account_id'], '')
        self.assertEqual(target['account_key'], '14100000240526')


if __name__ == '__main__':
    unittest.main()
