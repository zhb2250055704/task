import unittest

import server


class FakeCocosConnection:
    def __init__(self, verification_response):
        self.command_lock = server.threading.Lock()
        self.verification_response = verification_response
        self.calls = []

    def send_rpc(self, method, params):
        self.calls.append((method, params))
        if method == 'sendProtocol':
            return {'ok': True, 'result': 'Success'}
        return self.verification_response


class CocosCommandVerificationTest(unittest.TestCase):
    def test_parses_vip_level_command_verification(self):
        self.assertEqual(
            server.gm_command_verification_spec(' #SetVipLevel 12 '),
            {'type': 'vip_level', 'label': 'VIP 等级', 'expected': 12},
        )
        self.assertIsNone(server.gm_command_verification_spec('#money 43 100'))

    def test_vip_command_is_successful_only_after_actual_level_matches(self):
        connection = FakeCocosConnection({
            'ok': True,
            'result': {'ready': True, 'vipLevel': 12},
        })

        result = server._execute_cocos_connection(connection, ['#setVipLevel 12'])

        self.assertTrue(result['ok'])
        self.assertEqual(result['verification_status'], 'verified')
        self.assertEqual(result['verified_count'], 1)
        self.assertEqual(
            [method for method, _params in connection.calls],
            ['sendProtocol', 'getGmVerificationState'],
        )

    def test_old_client_is_reported_as_delivered_but_not_verified(self):
        connection = FakeCocosConnection({
            'ok': False,
            'error': "Method 'getGmVerificationState' not found",
        })

        result = server._execute_cocos_connection(connection, ['#setVipLevel 12'])

        self.assertFalse(result['ok'])
        self.assertEqual(result['delivery_status'], 'delivered')
        self.assertEqual(result['verification_status'], 'unsupported')
        self.assertIn('重新构建或刷新游戏', result['msg'])

    def test_unchanged_vip_level_is_a_verification_failure(self):
        connection = FakeCocosConnection({
            'ok': True,
            'result': {'ready': True, 'vipLevel': 3},
        })
        spec = server.gm_command_verification_spec('#setVipLevel 12')

        result = server._verify_cocos_command(connection, spec, timeout=0, interval=0)

        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'verification_failed')
        self.assertEqual(result['actual'], 3)
        self.assertEqual(result['expected'], 12)


if __name__ == '__main__':
    unittest.main()
