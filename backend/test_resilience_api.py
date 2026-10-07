"""Phase 7 drills through real WebSocket commands and live simulation ticks."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import main


class ResilienceSocketTests(unittest.TestCase):
    def read(self, ws):
        state = ws.receive_json()
        self.assertNotEqual('command_error', state['type'], state.get('message'))
        if getattr(self, 'original', None) is not None:
            cartons = [s['cargo_id'] for s in state['warehouse']['racks'] if s['state'] == 'stored']
            cartons += [r['task']['cargo_id'] for r in state['robots'] if r['task'] and (r['has_cargo'] or r['handling'])]
            self.assertEqual(len(cartons), len(set(cartons)))
            self.assertEqual(self.original, set(cartons))
        return state

    def until(self, ws, predicate):
        for _ in range(3000):
            state = self.read(ws)
            if predicate(state):
                return state
        self.fail('Expected live state did not arrive')

    def start(self, ws, number):
        self.original = None
        self.read(ws)
        ws.send_json({'action': 'switch_warehouse', 'warehouse_id': f'warehouse_{number}'})
        self.until(ws, lambda s: s['type'] == 'init' and s['warehouse']['id'] == f'warehouse_{number}')
        ws.send_json({'action': 'prepare_consolidation'})
        state = self.until(ws, lambda s: s['tasks']['consolidation']['status'] == 'ready')
        self.original = {s['cargo_id'] for s in state['warehouse']['racks'] if s['state'] == 'stored'}
        ws.send_json({'action': 'fill_empty_rack'})

    def pause_at(self, ws, predicate):
        for _ in range(20):
            self.until(ws, lambda s: any(predicate(r) for r in s['robots']) and s['sim']['running'])
            ws.send_json({'action': 'pause'})
            state = self.until(ws, lambda s: s['sim']['paused'])
            robot = next((r for r in state['robots'] if predicate(r)), None)
            if robot:
                return state, robot
            ws.send_json({'action': 'pause'})
        self.fail('No stable drill opportunity')

    def finish(self, ws):
        ws.send_json({'action': 'pause'})
        state = self.until(ws, lambda s: not s['sim']['running'])
        self.assertEqual('completed', state['tasks']['consolidation']['status'])
        self.assertEqual(0, state['tasks']['resilience']['collisions'])
        self.assertEqual(0, state['tasks']['resilience']['deadlocks'])
        return state

    def test_before_pickup_reauction_all_three_live_warehouses(self):
        with patch.object(main, 'TICK_INTERVAL', .002), TestClient(main.app) as client:
            for number in (1, 2, 3):
                with self.subTest(warehouse=number), client.websocket_connect('/ws') as ws:
                    self.start(ws, number)
                    _, robot = self.pause_at(ws, lambda r: r['available'] and r['task'] and not r['has_cargo'] and not r['handling'])
                    task_id, cargo_id = robot['task']['id'], robot['task']['cargo_id']
                    ws.send_json({'action': 'simulate_robot_failure', 'robot_id': robot['id']})
                    state = self.until(ws, lambda s: s['tasks']['resilience']['robot_failures'] == 1)
                    task = next(t for t in state['tasks']['pending'] if t['id'] == task_id)
                    self.assertEqual('recovery_pending', task['status'])
                    self.assertEqual('stored', task['cargo_state'])
                    self.assertTrue(any(s['cargo_id'] == cargo_id and s['state'] == 'stored' for s in state['warehouse']['racks']))
                    done = self.finish(ws)
                    event = done['tasks']['resilience']['events'][0]
                    self.assertNotEqual(robot['id'], event['recovery_robot_id'])
                    self.assertEqual('completed', event['status'])
                    self.assertEqual(1, done['tasks']['resilience']['successful_recoveries'])
                    print(f'WS WH{number} pre-pickup: task {task_id} reauctioned; completed, fleet parked, zero collisions/deadlocks')

    def test_carrying_failure_contact_handoff_and_restore_all_three(self):
        with patch.object(main, 'TICK_INTERVAL', .002), TestClient(main.app) as client:
            for number in (1, 2, 3):
                with self.subTest(warehouse=number), client.websocket_connect('/ws') as ws:
                    self.start(ws, number)
                    _, robot = self.pause_at(ws, lambda r: r['has_cargo'] and not r['handling'])
                    task_id, cargo_id, destination = robot['task']['id'], robot['task']['cargo_id'], robot['task']['dropoff_slot_code']
                    ws.send_json({'action': 'simulate_robot_failure', 'robot_id': robot['id']})
                    state = self.until(ws, lambda s: s['tasks']['resilience']['robot_failures'] == 1)
                    task = next(t for t in state['tasks']['pending'] if t['id'] == task_id)
                    self.assertEqual('recovery_required', task['cargo_state'])
                    self.assertEqual(f'robot:{robot["id"]}', task['cargo_owner'])
                    self.assertFalse(any(s['cargo_id'] == cargo_id and s['state'] == 'stored' for s in state['warehouse']['racks']))
                    ws.send_json({'action': 'pause'})
                    handoff = self.until(ws, lambda s: any(r['handling'] and r['handling']['place'] == 'recovery' for r in s['robots']))
                    receiver = next(r for r in handoff['robots'] if r['handling'] and r['handling']['place'] == 'recovery')
                    failed = next(r for r in handoff['robots'] if r['id'] == robot['id'])
                    self.assertEqual(1, abs(receiver['x']-failed['x'])+abs(receiver['y']-failed['y']))
                    self.assertFalse(failed['has_cargo'])
                    done = self.until(ws, lambda s: not s['sim']['running'])
                    self.assertEqual('completed', done['tasks']['consolidation']['status'])
                    metrics = done['tasks']['resilience']
                    self.assertEqual(1, metrics['cargo_recovered']); self.assertEqual(1, metrics['successful_recoveries'])
                    self.assertEqual(destination, metrics['events'][0]['destination'])
                    self.assertEqual(0, metrics['collisions']); self.assertEqual(0, metrics['deadlocks'])
                    ws.send_json({'action': 'restore_robot', 'robot_id': robot['id']})
                    restored = self.until(ws, lambda s: not next(r for r in s['robots'] if r['id'] == robot['id'])['failed'])
                    self.assertEqual((robot['x'], robot['y']), (next(r for r in restored['robots'] if r['id'] == robot['id'])['x'], next(r for r in restored['robots'] if r['id'] == robot['id'])['y']))
                    print(f'WS WH{number} carrying: cargo {cargo_id}, adjacent handoff, original {destination} filled; recovery {metrics["recovery_times_ticks"]} ticks; zero collisions/deadlocks')

    def test_communication_loss_and_bidirectional_reconciliation_all_three(self):
        with patch.object(main, 'TICK_INTERVAL', .002), TestClient(main.app) as client:
            for number in (1, 2, 3):
                with self.subTest(warehouse=number), client.websocket_connect('/ws') as ws:
                    self.start(ws, number)
                    state, robot = self.pause_at(ws, lambda r: r['has_cargo'] and not r['handling'])
                    ws.send_json({'action': 'simulate_communication_loss', 'robot_id': robot['id']})
                    offline = self.until(ws, lambda s: robot['id'] in s['network']['partitioned'])
                    local = next(r for r in offline['robots'] if r['id'] == robot['id'])
                    self.assertEqual('local', local['communication_mode'])
                    ws.send_json({'action': 'pause'})
                    moved = self.until(ws, lambda s: s['tick'] >= offline['tick']+3)
                    ws.send_json({'action': 'pause'})
                    frozen = self.until(ws, lambda s: s['sim']['paused'])
                    ws.send_json({'action': 'restore_communication', 'robot_id': robot['id']})
                    synced = self.until(ws, lambda s: s['tasks']['resilience']['reconciliations'] == 1)
                    current = next(r for r in synced['robots'] if r['id'] == robot['id'])
                    for peer in synced['robots']:
                        if peer['id'] == robot['id']:
                            continue
                        snapshot = peer['peer_states'][str(robot['id'])]
                        self.assertEqual((current['x'], current['y']), (snapshot['x'], snapshot['y']))
                        self.assertEqual(current['status'], snapshot['status'])
                        self.assertEqual(current['task']['id'] if current['task'] else None, snapshot['current_task'])
                        if current['task']:
                            task = next(t for t in synced['tasks']['active'] if t['id'] == current['task']['id'])
                            self.assertEqual(task['cargo_owner'], snapshot['cargo_owner'])
                            self.assertEqual(task['cargo_id'], snapshot['cargo_id'])
                            self.assertEqual(task['destination_label'].split(' / Slot ')[-1], snapshot['destination'])
                    done = self.finish(ws)
                    self.assertEqual(1, done['tasks']['resilience']['communication_loss_events'])
                    self.assertEqual(1, done['tasks']['resilience']['reconciliations'])
                    print(f'WS WH{number} communication: local mode, current custody/destination reconciled, mission completed')


if __name__ == '__main__':
    unittest.main()
