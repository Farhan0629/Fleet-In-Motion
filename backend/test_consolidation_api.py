"""Real WebSocket protocol integration, including default demo energy levels."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import main


class ConsolidationSocketTests(unittest.TestCase):
    def test_websocket_fill_all_three_warehouses_and_legacy_start(self):
        with patch.object(main, 'TICK_INTERVAL', 0), TestClient(main.app) as client:
            for number in (1, 2, 3):
                with self.subTest(warehouse=number), client.websocket_connect('/ws') as ws:
                    ws.receive_json()
                    ws.send_json({'action': 'switch_warehouse', 'warehouse_id': f'warehouse_{number}'})
                    init = ws.receive_json()
                    self.assertEqual(f'warehouse_{number}', init['warehouse']['id'])
                    # Phase 1-5 manifest is still the initial default; preparation is explicit.
                    self.assertTrue(init['tasks']['pending'])
                    self.assertTrue(all(t['stage'] == 'putaway' for t in init['tasks']['pending']))
                    ws.send_json({'action': 'prepare_consolidation'})
                    ready = ws.receive_json()
                    self.assertEqual('ready', ready['tasks']['consolidation']['status'])
                    target = ready['tasks']['consolidation']['target_rack']
                    original = {s['cargo_id'] for s in ready['warehouse']['racks'] if s['state'] == 'stored'}
                    self.assertTrue(original)
                    ws.send_json({'action': 'fill_empty_rack'})
                    phases = set()
                    for _ in range(2500):
                        state = ws.receive_json()
                        self.assertNotEqual('command_error', state['type'])
                        mission = state['tasks']['consolidation']
                        cargo = [s['cargo_id'] for s in state['warehouse']['racks'] if s['state'] == 'stored']
                        for robot in state['robots']:
                            if robot['task'] and (robot['handling'] or robot['has_cargo']):
                                cargo.append(robot['task']['cargo_id'])
                            if robot['handling']:
                                phases.add(robot['handling']['kind'])
                        self.assertEqual(len(cargo), len(set(cargo)))
                        self.assertEqual(original, set(cargo))
                        if mission['status'] == 'completed' and not state['sim']['running']:
                            break
                    else:
                        self.fail(f'Warehouse {number} protocol round did not complete')
                    self.assertEqual({'pickup', 'dropoff'}, phases)
                    self.assertEqual(mission['capacity'], mission['completed'])
                    self.assertEqual(100, mission['progress'])
                    self.assertEqual(0, mission['collision_count'])
                    self.assertEqual(0, mission['deadlock_count'])
                    self.assertTrue(all(s['state'] == 'stored' for s in state['warehouse']['racks'] if s['island'] == target))
                    print(f'WebSocket WH{number}: completed={mission["completed"]}, final_tick={state["tick"]}, fleet parked, default batteries')
            # The original start command still runs the original putaway manifest.
            with client.websocket_connect('/ws') as ws:
                ws.receive_json()
                ws.send_json({'action': 'switch_warehouse', 'warehouse_id': 'warehouse_1'})
                ws.receive_json()
                ws.send_json({'action': 'start'})
                for _ in range(2500):
                    state = ws.receive_json()
                    if not state['sim']['running']:
                        break
                self.assertEqual(state['tasks']['total_count'], state['tasks']['completed_count'])
                self.assertFalse(state['tasks']['consolidation']['enabled'])
                self.assertEqual(0, state['metrics']['collisions'])

    def test_timeout_and_resume_preserve_inventory_and_task_ids(self):
        with patch.object(main, 'TICK_INTERVAL', 0), patch.object(main, 'MAX_TICKS', 1), TestClient(main.app) as client, client.websocket_connect('/ws') as ws:
            ws.receive_json()
            ws.send_json({'action': 'switch_warehouse', 'warehouse_id': 'warehouse_1'})
            ws.receive_json()
            ws.send_json({'action': 'prepare_consolidation'})
            ready = ws.receive_json()
            original = {s['cargo_id'] for s in ready['warehouse']['racks'] if s['state'] == 'stored'}
            ws.send_json({'action': 'fill_empty_rack'})
            while True:
                state = ws.receive_json()
                if state['tasks']['consolidation']['status'] == 'timed_out':
                    break
            task_ids = {t['id'] for t in state['tasks']['pending'] + state['tasks']['active']}
            self.assertTrue(task_ids)
            with patch.object(main, 'MAX_TICKS', 2000):
                ws.send_json({'action': 'resume_consolidation'})
                for _ in range(2500):
                    state = ws.receive_json()
                    if not state['sim']['running']:
                        break
                self.assertEqual('completed', state['tasks']['consolidation']['status'])
                self.assertEqual(task_ids, {t['id'] for t in state['tasks']['completed']})
                self.assertEqual(original, {s['cargo_id'] for s in state['warehouse']['racks'] if s['state'] == 'stored'})

    def test_invalid_old_editor_command_is_rejected_and_failed_start_visible(self):
        with TestClient(main.app) as client, client.websocket_connect('/ws') as ws:
            ws.receive_json()
            ws.send_json({'action': 'switch_warehouse', 'warehouse_id': 'warehouse_1'})
            ws.receive_json()
            ws.send_json({'action': 'create_task', 'source': 'T01', 'destination': 'T07'})
            ws.receive_json()  # Updated state before actionable error.
            self.assertIn('Unknown', ws.receive_json()['message'])
            ws.send_json({'action': 'fill_empty_rack'})
            state = ws.receive_json()
            self.assertEqual('failed', state['tasks']['consolidation']['status'])
            self.assertEqual('command_error', ws.receive_json()['type'])


if __name__ == '__main__':
    unittest.main()
