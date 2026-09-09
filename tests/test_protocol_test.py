import tempfile
import time
import unittest
from unittest.mock import patch

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

    def test_token_event_baseline_loads_fishing_bait_actions(self):
        baseline = protocol_test.load_token_event_baseline(r'C:\Users\TU\Documents\excel')
        self.assertTrue(baseline['exists'])
        self.assertEqual(baseline['event']['event_id'], '5')
        self.assertEqual(baseline['event']['action_ids'], ['29', '30', '31', '32', '33', '34'])
        self.assertEqual(baseline['bait_item']['item_id'], '19948008')
        self.assertEqual(len(baseline['actions']), 6)
        self.assertEqual(baseline['actions_by_id']['29']['action_param'], 200)
        self.assertEqual(baseline['actions_by_id']['29']['configured_probability'], 0.02)
        self.assertEqual(baseline['actions_by_id']['30']['action_num'], 50)
        self.assertEqual(baseline['actions_by_id']['30']['limit'], 15)
        self.assertEqual(baseline['actions_by_id']['33']['configured_probability'], 0.4)

    def test_token_event_measurement_excludes_failed_and_reset_snapshots(self):
        action = {
            'action_id': '30', 'action_name': '消耗加速', 'token_item_id': '19948008',
            'token_item_name': '精制鱼饵', 'configured_probability': 0.03, 'limit': 15,
        }
        stats = protocol_test._new_stats()
        stats['requested'] = 100
        protocol_test._init_token_event_stats(stats, action)
        success = {'ok': True, 'response': {'metaId': 'a', 'tokenNumMap': {'30': 4}}}
        hit = {'ok': True, 'response': {'metaId': 'a', 'tokenNumMap': {'30': {'value': 5}}}}
        miss = {'ok': True, 'response': {'metaId': 'a', 'tokenNumMap': {'30': 5}}}
        reset = {'ok': True, 'response': {'metaId': 'a', 'tokenNumMap': {'30': 3}}}
        protocol_test._record_token_event_measurement(stats, success, hit, action)
        protocol_test._record_token_event_measurement(stats, hit, miss, action)
        protocol_test._record_token_event_measurement(stats, miss, reset, action)
        protocol_test._record_token_event_measurement(stats, miss, {'ok': False}, action)
        report = protocol_test._token_event_report(
            stats,
            {'event': {'event_id': '5'}, 'actions': [action], 'actions_by_id': {'30': action}},
            {'token_event': {'query_protocol': 'CgTokenEventActivityInfo'}},
        )
        self.assertEqual(report['observed_samples'], 2)
        self.assertEqual(report['bait_hits'], 1)
        self.assertEqual(report['bait_total'], 1)
        self.assertEqual(report['probability'], 0.5)
        self.assertEqual(report['counter_resets'], 1)
        self.assertEqual(report['snapshot_failures'], 1)
        self.assertEqual(report['coverage'], 0.02)

    def test_fishing_bait_service_queries_before_and_after_each_action(self):
        action = {
            'action_id': '29', 'action_type': 1, 'action_name': '消耗元宝',
            'action_num': 0, 'action_param': 200, 'configured_probability': 0.02,
            'token_item_id': '19948008', 'token_item_name': '精制鱼饵',
            'token_count': 1, 'limit': None,
        }
        baseline = {
            'event': {'event_id': '5'},
            'actions': [action],
            'actions_by_id': {'29': action},
            'bait_item': {'item_id': '19948008', 'name': '精制鱼饵'},
        }
        with tempfile.TemporaryDirectory() as runtime_dir, patch.object(
            protocol_test, 'load_token_event_baseline', return_value=baseline
        ):
            calls = []
            token_count = 0
            action_count = 0

            def send_request(request_protocol, payload, response_protocol, timeout_ms, response_match):
                nonlocal token_count, action_count
                calls.append((request_protocol, dict(payload)))
                if request_protocol == 'CgTokenEventActivityInfo':
                    return {'ok': True, 'response_protocol': response_protocol, 'response': {
                        'metaId': payload['metaId'], 'tokenNumMap': {'29': token_count},
                    }}
                action_count += 1
                if action_count in (1, 3):
                    token_count += 1
                return {'ok': True, 'response_protocol': response_protocol, 'response': {'code': 0}}

            service = protocol_test.ProtocolTestService(runtime_dir, 'missing-client', 'missing-excel')
            result = service.start({
                'title': 'bait',
                'fixture': 'fishing-bait',
                'target_specs': [{'connection_id': 'direct:test'}],
                'request': {
                    'protocol': 'CgSpendGold',
                    'payload': {'amount': 200},
                    'response_protocol': 'GcSpendGoldResult',
                    'success_condition': 'code == 0',
                },
                'token_event': {
                    'activity_meta_id': 'activity-a',
                    'action_id': '29',
                },
                'count': 3,
            }, send_request)
            run_id = result['run']['id']
            deadline = time.time() + 3
            while service.get(run_id).get('status') in ('queued', 'running') and time.time() < deadline:
                time.sleep(0.01)
            report = service.report(run_id)
            token_report = report['token_event']
            self.assertEqual([item[0] for item in calls], [
                'CgTokenEventActivityInfo', 'CgSpendGold', 'CgTokenEventActivityInfo',
                'CgTokenEventActivityInfo', 'CgSpendGold', 'CgTokenEventActivityInfo',
                'CgTokenEventActivityInfo', 'CgSpendGold', 'CgTokenEventActivityInfo',
            ])
            self.assertTrue(all(item[1]['metaId'] == 'activity-a' for item in calls if item[0] == 'CgTokenEventActivityInfo'))
            self.assertEqual(token_report['action_successes'], 3)
            self.assertEqual(token_report['observed_samples'], 3)
            self.assertEqual(token_report['bait_hits'], 2)
            self.assertEqual(token_report['bait_total'], 2)
            self.assertAlmostEqual(token_report['probability'], 2 / 3)

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

    def test_fishing_bait_rejects_empty_behavior_payload_before_execution(self):
        plan = protocol_test.normalize_plan({
            'fixture': 'fishing-bait',
            'request': {
                'protocol': 'CgItemBuy',
                'payload': {},
                'response_protocol': 'GcItemBuy',
            },
            'token_event': {'activity_meta_id': 'meta-1', 'action_id': '29'},
        })
        errors = protocol_test.validate_plan(plan, require_target=False, token_baseline={
            'actions_by_id': {'29': {'action_type': 1}},
        })
        self.assertTrue(any('items' in item and 'metaId' in item for item in errors))

    def test_fishing_bait_accepts_item_buy_payload(self):
        plan = protocol_test.normalize_plan({
            'fixture': 'fishing-bait',
            'request': {
                'protocol': 'CgItemBuy',
                'payload': {'items': [{'metaId': '19948008', 'count': 1}]},
                'response_protocol': 'GcItemBuy',
            },
            'token_event': {'activity_meta_id': 'meta-1', 'action_id': '29'},
        })
        errors = protocol_test.validate_plan(plan, require_target=False, token_baseline={
            'actions_by_id': {'29': {'action_type': 1}},
        })
        self.assertFalse(any('items' in item for item in errors))

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

    def test_service_restart_recovers_orphaned_running_run(self):
        with tempfile.TemporaryDirectory() as runtime_dir:
            run_dir = protocol_test.os.path.join(runtime_dir, 'pt-orphaned-run')
            protocol_test.os.makedirs(run_dir)
            state = {
                'id': 'pt-orphaned-run',
                'title': 'orphaned',
                'fixture': 'generic',
                'status': 'running',
                'finished_at_ms': 0,
                'message': '正在停止测试',
                'plan': {'count': 10},
            }
            protocol_test._write_json(protocol_test.os.path.join(run_dir, 'run.json'), state)

            service = protocol_test.ProtocolTestService(runtime_dir, 'missing-client', 'missing-excel')

            recovered = service.get('pt-orphaned-run')
            self.assertEqual(recovered['status'], 'stopped')
            self.assertEqual(recovered['message'], '服务重启，测试已自动停止')
            self.assertGreater(recovered['finished_at_ms'], 0)

    def test_stop_without_live_worker_finishes_run_immediately(self):
        with tempfile.TemporaryDirectory() as runtime_dir:
            service = protocol_test.ProtocolTestService(runtime_dir, 'missing-client', 'missing-excel')
            state = {
                'id': 'pt-no-worker',
                'title': 'no-worker',
                'fixture': 'generic',
                'status': 'running',
                'finished_at_ms': 0,
                'message': '正在停止测试',
                'plan': {'count': 10},
            }
            protocol_test._write_json(
                protocol_test.os.path.join(runtime_dir, 'pt-no-worker', 'run.json'), state
            )
            with service.lock:
                service.runs[state['id']] = dict(state)

            result = service.stop(state['id'])

            self.assertTrue(result['ok'])
            self.assertEqual(result['run']['status'], 'stopped')
            self.assertEqual(result['run']['message'], '测试已停止（执行线程已退出）')
            self.assertGreater(result['run']['finished_at_ms'], 0)
            self.assertEqual(service.get(state['id'])['status'], 'stopped')

    def test_stop_signals_live_worker_and_keeps_stopping_message(self):
        with tempfile.TemporaryDirectory() as runtime_dir:
            service = protocol_test.ProtocolTestService(runtime_dir, 'missing-client', 'missing-excel')
            stop_event = protocol_test.threading.Event()
            worker = protocol_test.threading.Thread(target=lambda: stop_event.wait(2), daemon=True)
            state = {
                'id': 'pt-live-worker',
                'title': 'live-worker',
                'fixture': 'generic',
                'status': 'running',
                'finished_at_ms': 0,
                'message': '正在执行协议测试',
                'plan': {'count': 10},
            }
            protocol_test._write_json(
                protocol_test.os.path.join(runtime_dir, 'pt-live-worker', 'run.json'), state
            )
            with service.lock:
                service.runs[state['id']] = dict(state)
                service.stop_events[state['id']] = stop_event
                service.workers[state['id']] = worker
            worker.start()

            result = service.stop(state['id'])
            worker.join(1)

            self.assertTrue(result['ok'])
            self.assertEqual(result['run']['status'], 'running')
            self.assertEqual(result['run']['message'], '正在停止测试')
            self.assertTrue(stop_event.is_set())


if __name__ == '__main__':
    unittest.main()
