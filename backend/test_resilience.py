"""Deterministic recovery and reconnect scenarios without another allocator."""
import unittest
from unittest.mock import patch

from collision import detect_collisions, detect_deadlock, resolve_deadlock
from p2p import P2PMessage
from test_dynamic_tasks import setup, audit_inventory


def step(warehouse, manager, fleet, network, tick):
    manager.resilience.refresh(fleet, network, tick)
    manager.consolidation.refresh(fleet, tick)
    manager.allocate_tasks(fleet, network, tick=tick)
    for robot in fleet:
        action = robot.tick(tick, network)
        if action == 'handling' and robot.handling['kind'] == 'pickup' and robot.handling['progress'] == 0:
            manager.note_pickup(robot.handling['task_id'])
        elif action == 'picked_up':
            manager.note_pickup(robot.current_task['id'])
        elif action == 'delivered':
            outcome, _ = manager.complete_leg(robot.last_delivered_task_id, tick=tick)
            assert outcome == 'stored'
        manager.resilience.action(robot, action, fleet, network, tick)
    manager.consolidation.collisions += len(detect_collisions(fleet))
    deadlocks = detect_deadlock(fleet)
    if deadlocks:
        manager.consolidation.deadlocks += len(deadlocks)
        resolve_deadlock(fleet, deadlocks, warehouse, network, tick)
    manager.consolidation.refresh(fleet, tick)


def carrying_setup(number=1):
    warehouse, manager, fleet, network = setup(number)
    original = {s['cargo_id'] for s in warehouse.stored_slots()}
    manager.consolidation.start(fleet)
    for tick in range(1, 200):
        step(warehouse, manager, fleet, network, tick)
        audit_inventory(warehouse, manager, fleet, original)
        carrier = next((r for r in fleet if r.carrying and not r.handling), None)
        if carrier:
            return warehouse, manager, fleet, network, original, carrier, tick
    raise AssertionError('No carrying robot found')


class ResilienceTests(unittest.TestCase):
    def test_before_pickup_release_and_original_task_reauction_all_warehouses(self):
        for number in (1, 2, 3):
            with self.subTest(warehouse=number):
                warehouse, manager, fleet, network = setup(number)
                original = {s['cargo_id'] for s in warehouse.stored_slots()}
                manager.consolidation.start(fleet)
                manager.allocate_tasks(fleet, network, tick=1)
                task = manager.active_tasks[0]
                source, destination = task.pickup_slot_id, task.dropoff_slot_id
                failed = next(r for r in fleet if r.id == task.assigned_to)
                manager.resilience.fail_robot(failed, fleet, network, 1)
                self.assertEqual('recovery_pending', task.status)
                self.assertEqual('stored', warehouse.get_slot(source)['state'])
                self.assertIsNone(warehouse.get_slot(source)['task_id'])
                self.assertEqual('empty', warehouse.get_slot(destination)['state'])
                self.assertFalse(failed.carrying)
                for tick in range(2, 1000):
                    step(warehouse, manager, fleet, network, tick)
                    audit_inventory(warehouse, manager, fleet, original)
                    if manager.consolidation.status == 'completed':
                        break
                self.assertEqual('completed', manager.consolidation.status)
                self.assertNotEqual(failed.id, task.assigned_to)
                self.assertEqual(destination, task.dropoff_slot_id)
                self.assertEqual(1, manager.resilience.successful_recoveries)
                self.assertEqual(1, manager.resilience.tasks_reassigned)
                self.assertEqual(0, manager.resilience.cargo_recovered)
                self.assertEqual(0, manager.consolidation.collisions)
                self.assertEqual(0, manager.consolidation.deadlocks)
                print(f'WH{number} before pickup: complete at {tick}; zero collisions/deadlocks')

    def test_carrying_recovery_physical_handoff_and_completion_all_warehouses(self):
        for number in (1, 2, 3):
            with self.subTest(warehouse=number):
                warehouse, manager, fleet, network, original, failed, fail_tick = carrying_setup(number)
                task = manager.find_task(failed.current_task['id'])
                identity = (task.id, task.cargo_id, task.dropoff_slot_id, task.destination)
                fail_cell = (failed.x, failed.y)
                manager.resilience.fail_robot(failed, fleet, network, fail_tick)
                self.assertEqual('recovery_pending', task.status)
                self.assertEqual('recovery_required', task.cargo_state)
                self.assertEqual(f'robot:{failed.id}', task.cargo_owner)
                self.assertTrue(failed.carrying)
                self.assertEqual('empty', warehouse.get_slot(task.pickup_slot_id)['state'])
                self.assertEqual('reserved', warehouse.get_slot(task.dropoff_slot_id)['state'])
                with self.assertRaisesRegex(ValueError, 'recovered'):
                    manager.resilience.restore_robot(failed, fleet, network, fail_tick)
                handoff_seen = False
                for tick in range(fail_tick+1, 1500):
                    step(warehouse, manager, fleet, network, tick)
                    audit_inventory(warehouse, manager, fleet, original)
                    self.assertEqual(fail_cell, (failed.x, failed.y))
                    self.assertEqual(identity, (task.id, task.cargo_id, task.dropoff_slot_id, task.destination))
                    if task.cargo_state == 'handoff':
                        recovery = next(r for r in fleet if r.id == task.recovery_robot_id)
                        self.assertEqual(1, abs(recovery.x-failed.x)+abs(recovery.y-failed.y))
                        self.assertEqual('recovery', recovery.handling['place'])
                        self.assertEqual(list(fail_cell), recovery.handling['target'])
                        self.assertFalse(failed.carrying)
                        self.assertEqual(f'robot:{recovery.id}', task.cargo_owner)
                        self.assertIsNone(failed.current_task)
                        handoff_seen = True
                    if manager.consolidation.status == 'completed':
                        break
                self.assertTrue(handoff_seen)
                self.assertEqual('completed', manager.consolidation.status)
                self.assertEqual('stored', task.cargo_state)
                self.assertEqual(f'rack:{task.dropoff_slot_code}', task.cargo_owner)
                self.assertEqual(1, manager.resilience.cargo_recovered)
                self.assertEqual(1, manager.resilience.successful_recoveries)
                self.assertEqual([manager.resilience.records[0]["completion_tick"]-fail_tick], manager.resilience.recovery_ticks)
                self.assertEqual(0, manager.consolidation.collisions)
                self.assertEqual(0, manager.consolidation.deadlocks)
                manager.resilience.restore_robot(failed, fleet, network, tick)
                self.assertTrue(failed.available); self.assertFalse(failed.failed)
                self.assertEqual(fail_cell, (failed.x, failed.y))
                print(f'WH{number} carrying: fail {fail_tick}, handoff {manager.resilience.records[0]["handoff_tick"]}, delivery {manager.resilience.records[0]["completion_tick"]}, mission {tick}; zero collisions/deadlocks')

    def test_communication_loss_local_safety_reconnect_all_warehouses(self):
        for number in (1, 2, 3):
            with self.subTest(warehouse=number):
                warehouse, manager, fleet, network, original, robot, tick = carrying_setup(number)
                peer = next(r for r in fleet if r.id != robot.id)
                task = manager.find_task(robot.current_task['id'])
                peer.known_peer_intents[robot.id] = [(0, 0)]
                manager.resilience.lose_communication(robot, fleet, network, tick)
                self.assertEqual('local', robot.communication_mode)
                self.assertNotIn(robot.id, peer.known_peer_intents)
                self.assertEqual({}, robot.known_peer_positions)
                for current in range(tick+1, tick+4):
                    step(warehouse, manager, fleet, network, current)
                    audit_inventory(warehouse, manager, fleet, original)
                    self.assertEqual([], network.receive_all(robot.id))
                manager.resilience.restore_communication(robot, fleet, network, tick+3)
                self.assertEqual('online', robot.communication_mode)
                snapshot = peer.known_peer_states[robot.id]
                self.assertEqual((robot.x, robot.y), (snapshot['x'], snapshot['y']))
                self.assertEqual(task.id, snapshot['current_task'])
                self.assertEqual(task.cargo_id, snapshot['cargo_id'])
                self.assertEqual(task.cargo_owner, snapshot['cargo_owner'])
                self.assertEqual(task.dropoff_slot_code, snapshot['destination'])
                self.assertEqual(task.status, snapshot['task_status'])
                self.assertEqual('empty', warehouse.get_slot(task.pickup_slot_id)['state'])
                self.assertTrue(robot.known_peer_states)  # Bidirectional refresh.
                for current in range(tick+4, 1000):
                    step(warehouse, manager, fleet, network, current)
                    audit_inventory(warehouse, manager, fleet, original)
                    if manager.consolidation.status == 'completed':
                        break
                self.assertEqual('completed', manager.consolidation.status)
                self.assertEqual(0, manager.consolidation.collisions)
                self.assertEqual(0, manager.consolidation.deadlocks)
                self.assertEqual(1, manager.resilience.communication_losses)
                self.assertEqual(1, manager.resilience.reconciliations)

    def test_old_packets_and_old_snapshots_cannot_override_reconnect(self):
        _, manager, fleet, network = setup()
        robot, peer = fleet[:2]
        network.broadcast(robot.id, 'pos', {'x': 999, 'y': 999, 'tick': 10000})
        old_epoch = network.epochs[robot.id]
        manager.resilience.lose_communication(robot, fleet, network, 5)
        manager.resilience.restore_communication(robot, fleet, network, 6)
        self.assertEqual((robot.x, robot.y, 6), peer.known_peer_positions[robot.id])
        network.inboxes[peer.id].put_nowait(P2PMessage(robot.id, 'pos', {'x':999,'y':999,'tick':10000}, epoch=old_epoch))
        self.assertEqual([], network.receive_all(peer.id))
        before = dict(peer.known_peer_states[robot.id])
        stale = dict(before, x=999, tick=10000)
        peer._process_messages([P2PMessage(robot.id, 'state_sync', stale, epoch=old_epoch)], tick=7)
        self.assertEqual(before, peer.known_peer_states[robot.id])
        peer._process_messages([P2PMessage(robot.id, 'intent', {'path':[(999,999)],'tick':10000}, epoch=old_epoch)], tick=7)
        self.assertNotIn((999,999), peer.known_peer_intents.get(robot.id, []))
        peer._expire_peer_memory(20)
        self.assertNotIn(robot.id, peer.known_peer_states)

    def test_remote_handoff_and_unreachable_recovery_retain_owner(self):
        warehouse, manager, fleet, network, original, failed, tick = carrying_setup()
        task = manager.find_task(failed.current_task['id'])
        manager.resilience.fail_robot(failed, fleet, network, tick)
        other = next(r for r in fleet if r.id != failed.id)
        with self.assertRaisesRegex(ValueError, 'beside'):
            manager.resilience.begin_handoff(other, fleet, network, tick)
        x, y = failed.x, failed.y
        warehouse.blocked_cells.update(((x-1,y),(x+1,y),(x,y-1),(x,y+1)))
        for robot in fleet:
            if robot.id != failed.id:
                self.assertIsNone(manager.resilience.auction_payload(task, robot))
        self.assertEqual(f'robot:{failed.id}', task.cargo_owner)
        self.assertTrue(failed.carrying)
        audit_inventory(warehouse, manager, fleet, original)

    def test_transfer_failure_is_rejected_and_offline_robot_cannot_bid(self):
        warehouse, manager, fleet, network = setup()
        manager.consolidation.start(fleet)
        robot = fleet[0]
        manager.resilience.lose_communication(robot, fleet, network, 0)
        assignments = manager.allocate_tasks(fleet, network, tick=1)
        self.assertNotIn(robot.id, [a['robot_id'] for a in assignments])
        for tick in range(1, 100):
            step(warehouse, manager, fleet, network, tick)
            handler = next((r for r in fleet if r.handling), None)
            if handler:
                with self.assertRaisesRegex(ValueError, 'physical lift'):
                    manager.resilience.fail_robot(handler, fleet, network, tick)
                break
        else:
            self.fail('No handling dwell found')

    def test_failed_offline_carrier_reconciles_recovery_custody_and_finishes(self):
        warehouse, manager, fleet, network, original, failed, tick = carrying_setup(3)
        task = manager.find_task(failed.current_task['id'])
        manager.resilience.lose_communication(failed, fleet, network, tick)
        manager.resilience.fail_robot(failed, fleet, network, tick)
        manager.resilience.restore_communication(failed, fleet, network, tick)
        for peer in fleet:
            if peer.id == failed.id:
                continue
            snap = peer.known_peer_states[failed.id]
            self.assertEqual('failed', snap['status'])
            self.assertEqual('recovery_pending', snap['task_status'])
            self.assertEqual(f'robot:{failed.id}', snap['cargo_owner'])
            self.assertEqual(task.dropoff_slot_code, snap['destination'])
        for current in range(tick+1, 1500):
            step(warehouse, manager, fleet, network, current)
            audit_inventory(warehouse, manager, fleet, original)
            if manager.consolidation.status == 'completed':
                break
        self.assertEqual('completed', manager.consolidation.status)
        self.assertEqual(1, manager.resilience.cargo_recovered)
        self.assertEqual(0, manager.consolidation.collisions)
        self.assertEqual(0, manager.consolidation.deadlocks)

    def test_conflicting_custody_cannot_be_reconciled(self):
        _, manager, fleet, network, _, robot, tick = carrying_setup()
        task = manager.find_task(robot.current_task['id'])
        manager.resilience.lose_communication(robot, fleet, network, tick)
        task.cargo_owner = 'robot:999'
        with self.assertRaisesRegex(ValueError, 'conflicting cargo'):
            manager.resilience.restore_communication(robot, fleet, network, tick)
        self.assertTrue(network.is_partitioned[robot.id])
        self.assertEqual('local', robot.communication_mode)


if __name__ == '__main__':
    unittest.main()
