import tempfile
import time
import unittest

import protocol_test


class ProtocolTestTest(unittest.TestCase):
    def test_extract_config_records_uses_display_name_before_localization_key(self):
        rows = [
            {'row': 2, 'values': ['id', '', 'name', 'quality', 'weight', 'crownWeight', 'reward']},
            {'row': 3, 'values': ['int', '', 'string', 'string', 'string', 'string', 'int']},
            {'row': 4, 'values': ['1', '', '1', '1', '1', '1', '1']},
            {'row': 11, 'values': ['2007', '鳙鱼', 'FISH_EVENT_FISH_2007', '3', '10|40', '40', '6341012']},
        ]
        records = protocol_test._extract_config_records(
            rows, ['id', 'name', 'quality', 'weight', 'crownWeight', 'reward']
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['name'], '鳙鱼')
        self.assertEqual(records[0]['name_key'], 'FISH_EVENT_FISH_2007')

    def test_fishing_report_includes_ground_name_and_fish_quality_config(self):
        stats = protocol_test._new_stats()
        protocol_test._record_fishes(
            stats,
            [
                {'fishId': 2007, 'weight': 4},
                {'fishId': 2007, 'weight': 7},
                {'fishId': 2007, 'weight': 10},
            ],
            1,
        )
        report = protocol_test._build_report(
            {
                'id': 'pt-test',
                'title': 'fishing',
                'fixture': 'fishing',
                'status': 'succeeded',
                'plan': {'request_payload': {'scene': 1}},
            },
            stats,
            {
                'fishing_grounds': {'1': {'name': '赤壁江边'}},
                'fish_configs': {
                    '2007': {
                        'fish_id': '2007',
                        'name': '鳙鱼',
                        'name_key': 'FISH_EVENT_FISH_2007',
                        'quality': 3,
                        'quality_display': '3（稀有）',
                        'weight_range': '10|40',
                        'crown_weight': '40',
                        'reward_id': '6341012',
                    },
                },
            },
        )
        drop = report['drops']['fish_distribution'][0]
        self.assertEqual(report['fishing_ground']['name'], '赤壁江边')
        self.assertEqual(drop['fishing_ground_name'], '赤壁江边')
        self.assertEqual(drop['fish_name'], '鳙鱼')
        self.assertEqual(drop['config']['quality_display'], '3（稀有）')
        self.assertEqual(drop['config']['weight_range'], '10|40')
        self.assertEqual(drop['observed_weight']['sample_count'], 3)
        self.assertEqual(drop['observed_weight']['min'], 4)
        self.assertEqual(drop['observed_weight']['max'], 10)
        self.assertEqual(drop['observed_weight']['average'], 7)

    def test_wilson_interval_contains_observed_rate(self):
        interval = protocol_test.wilson_interval(300, 1000)
        self.assertLess(interval['low'], 0.3)
        self.assertGreater(interval['high'], 0.3)

    def test_generic_report_uses_response_statistics_without_fish_data(self):
        stats = protocol_test._new_stats()
        protocol_test._record_response(stats, 'GcActivityResult', {
            'code': 0,
            'current': {'fishes': [{'fishId': 2007}]},
        })
        protocol_test._record_response(stats, 'GcActivityResult', {'code': 1})
        report = protocol_test._build_report(
            {
                'id': 'pt-generic',
                'title': 'activity',
                'fixture': 'generic',
                'status': 'succeeded',
                'plan': {'request_payload': {}},
            },
            stats,
            None,
        )
        self.assertIsNone(report['fishing_ground'])
        self.assertEqual(report['drops']['fish_total'], 0)
        self.assertEqual(report['drops']['fish_distribution'], [])
        self.assertEqual(report['generic']['response_total'], 2)
        self.assertEqual(report['generic']['response_by_protocol']['GcActivityResult'], 2)
        self.assertEqual(report['generic']['response_code_by_protocol']['GcActivityResult'], {'0': 1, '1': 1})
        self.assertEqual(report['generic']['samples'][0]['keys'], ['code', 'current'])

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

    def test_generic_run_does_not_record_fish_fields(self):
        with tempfile.TemporaryDirectory() as runtime_dir:
            service = protocol_test.ProtocolTestService(runtime_dir, 'missing-client', 'missing-excel')

            def send_request(*args):
                return {
                    'ok': True,
                    'response_protocol': 'GcActivityResult',
                    'response': {
                        'code': 0,
                        'current': {'fishes': [{'fishId': 2007, 'weight': 4}]},
                    },
                }

            result = service.start({
                'title': 'generic-response',
                'fixture': 'generic',
                'target_specs': [{'connection_id': 'direct:test'}],
                'request': {
                    'protocol': 'CgActivityRequest',
                    'payload': {},
                    'response_protocol': 'GcActivityResult',
                },
                'count': 2,
                'concurrency': 1,
            }, send_request)
            self.assertTrue(result['ok'])
            run_id = result['run']['id']
            deadline = time.time() + 3
            while service.get(run_id).get('status') in ('queued', 'running') and time.time() < deadline:
                time.sleep(0.01)
            report = service.report(run_id)
            self.assertEqual(report['generic']['response_total'], 2)
            self.assertEqual(report['generic']['response_by_protocol']['GcActivityResult'], 2)
            self.assertEqual(report['drops']['fish_total'], 0)
            self.assertEqual(report['drops']['fish_by_id'], {})


if __name__ == '__main__':
    unittest.main()
