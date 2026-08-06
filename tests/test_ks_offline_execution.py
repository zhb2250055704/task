import json
import os
import tempfile
import unittest
from unittest import mock

import server


class KsOfflineExecutionTest(unittest.TestCase):
    def test_created_account_is_ks_dispatchable_without_online_client(self):
        catalog = {
            'catalog': {
                'categories': [],
                'environments': [{
                    'key': 'env-206',
                    'app_name': 'test-206',
                    'login_url': 'https://login-test-206.example.com',
                    'is_public': False,
                    'accounts': [{
                        'cache_id': 'account-cache-id',
                        'account_name': '141.A.account.268397',
                        'role_id': '14100000240327',
                        'server_id': '141',
                    }],
                }],
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = os.path.join(temp_dir, 'gm_account_cache.json')
            with open(cache_file, 'w', encoding='utf-8') as handle:
                json.dump(catalog, handle)
            with mock.patch.object(server, 'KS_ACCOUNT_CACHE_FILE', cache_file), \
                    mock.patch.object(server, 'load_ks_config', return_value={'token': 'valid'}), \
                    mock.patch.object(server, 'ks_token_status', return_value={
                        'configured': True,
                        'expired': False,
                        'expires_at': 0,
                        'profile': {},
                    }):
                result = server.ks_catalog_with_online([])

        account = result['environments'][0]['accounts'][0]
        self.assertFalse(account['dispatchable'])
        self.assertTrue(account['ks_dispatchable'])
        self.assertEqual(result['executable_count'], 1)

    def test_offline_targets_are_routed_to_ks(self):
        ks_result = {
            'ok': True,
            'target_count': 1,
            'delivered_count': 1,
            'batch_results': [],
        }
        with mock.patch.object(server, 'execute_ks_commands', return_value=ks_result) as execute_ks:
            result = server.execute_gm_commands(
                '#setStoryEvent 7 7000006',
                ks_targets=[{'environment_key': 'env-206', 'cache_id': 'account-cache-id'}],
            )

        self.assertTrue(result['ok'])
        self.assertEqual(result['channels'], ['ks'])
        execute_ks.assert_called_once()

    def test_online_and_offline_targets_are_combined(self):
        cocos_result = {
            'ok': True,
            'target_count': 1,
            'delivered_count': 1,
            'batch_results': [],
        }
        ks_result = {
            'ok': True,
            'target_count': 2,
            'delivered_count': 2,
            'batch_results': [],
        }
        with mock.patch.object(server, 'execute_cocos_commands', return_value=cocos_result), \
                mock.patch.object(server, 'execute_ks_commands', return_value=ks_result):
            result = server.execute_gm_commands(
                '#test',
                target_specs=[{'connection_id': 'client-1'}],
                ks_targets=[
                    {'environment_key': 'env-206', 'cache_id': 'account-1'},
                    {'environment_key': 'env-206', 'cache_id': 'account-2'},
                ],
            )

        self.assertTrue(result['ok'])
        self.assertEqual(result['channels'], ['cocos', 'ks'])
        self.assertEqual(result['target_count'], 3)
        self.assertEqual(result['delivered_count'], 3)


if __name__ == '__main__':
    unittest.main()
