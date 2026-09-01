import tempfile
import time
import unittest

import protocol_test


class ProtocolTestTest(unittest.TestCase):
    def test_wilson_interval_contains_observed_rate(self):
        interval = protocol_test.wilson_interval(300, 1000)
        self.assertLess(interval['low'], 0.3)
        self.assertGreater(interval['high'], 0.3)

    def test_normalize_rejects_parallel_execution(self):
        plan = protocol_test.normalize_plan({
            'request_protocol': 'CgFishStart',
            'response_protocol': 'GcFishStartResult',
            'concurrency': 2,
        })
        errors = protocol_test.validate_plan(plan, require_target=False)
        self.assertTrue(any('串行' in item for item in errors))

    def test_run_persists_events_and_fish_report(self):
        with tempfile.TemporaryDirectory() as runtime_dir:
            service = protocol_test.ProtocolTestService(runtime_dir, 'missing-client', 'missing-excel')

            def send_request(request_protocol, payload, response_protocol, timeout_ms, response_match):
                if request_protocol == 'CgFishFinish':
                    return {'ok': True, 'response_protocol': response_protocol, 'response': {'code': 0}}
                return {
                    'ok': True,
                    'response_protocol': response_protocol,
                    'response': {
                        'activityMetaId': payload['activityMetaId'],
                        'code': 0,
                        'current': {
                            'fishes': [
                                {'fishId': 2007, 'weight': 4, 'mask': 0, 'items': []},
                                {'fishId': 2006, 'weight': 5, 'mask': 1, 'items': []},
                            ],
                        },
                    },
                }

            result = service.start({
                'title': 'test',
                'fixture': 'fishing',
                'target_specs': [{'connection_id': 'direct:test'}],
                'request': {
                    'protocol': 'CgFishStart',
                    'payload': {'activityMetaId': 'activity-1', 'times': 1, 'scene': 1},
                    'response_protocol': 'GcFishStartResult',
                    'response_match': {'activityMetaId': 'activity-1'},
                    'success_condition': 'code == 0',
                },
                'finish': {
                    'protocol': 'CgFishFinish',
                    'response_protocol': 'GcFishFinishResult',
                    'payload': {'activityMetaId': 'activity-1'},
                },
                'count': 3,
                'concurrency': 1,
            }, send_request)
            self.assertTrue(result['ok'])
            run_id = result['run']['id']
            deadline = time.time() + 3
            while service.get(run_id).get('status') in ('queued', 'running') and time.time() < deadline:
                time.sleep(0.01)
            run = service.get(run_id)
            self.assertEqual(run['status'], 'succeeded')
            self.assertEqual(run['completed'], 3)
            report = service.report(run_id)
            self.assertEqual(report['drops']['fish_total'], 6)
            self.assertEqual(report['drops']['fish_by_id']['2007'], 3)
            self.assertEqual(len(service.events(run_id)), 3)

    def test_fatal_identity_error_stops_remaining_actions(self):
        with tempfile.TemporaryDirectory() as runtime_dir:
            service = protocol_test.ProtocolTestService(runtime_dir, 'missing-client', 'missing-excel')
            calls = []

            def send_request(*args):
                calls.append(args[0])
                return {'ok': False, 'code': 'identity_changed', 'error': 'target identity changed'}

            result = service.start({
                'title': 'identity-stop',
                'fixture': 'generic',
                'target_specs': [{'connection_id': 'direct:test'}],
                'request': {
                    'protocol': 'CgTestRequest',
                    'payload': {},
                    'response_protocol': 'GcTestResponse',
                },
                'count': 10,
                'concurrency': 1,
            }, send_request)
            self.assertTrue(result['ok'])
            run_id = result['run']['id']
            deadline = time.time() + 3
            while service.get(run_id).get('status') in ('queued', 'running') and time.time() < deadline:
                time.sleep(0.01)
            run = service.get(run_id)
            self.assertEqual(run['status'], 'failed')
            self.assertEqual(run['completed'], 1)
            self.assertEqual(calls, ['CgTestRequest'])


if __name__ == '__main__':
    unittest.main()
