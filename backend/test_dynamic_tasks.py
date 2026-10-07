"""Phase 6: inventory → deterministic tasks → existing auction → real transfers."""
from pathlib import Path
import unittest
from unittest.mock import patch

from collision import detect_collisions, detect_deadlock, resolve_deadlock
from p2p import P2PNetwork
from presentation_robot import PresentationRobot
from task_manager import TaskManager
from warehouse import Warehouse

WAREHOUSES = Path(__file__).parent / 'warehouses'


def setup(number=1):
    warehouse = Warehouse.compile_from_file(WAREHOUSES / f'warehouse_{number}.json')
    manager = TaskManager(warehouse)
    manager.consolidation.prepare()
    fleet = [PresentationRobot(i+1, pos, warehouse, 100) for i, pos in enumerate(warehouse.robot_starts[:warehouse.num_robots])]
    network = P2PNetwork()
    for robot in fleet:
        network.register_robot(robot.id)
    return warehouse, manager, fleet, network


def audit_inventory(warehouse, manager, fleet, original):
    # At dwell-start the carton leaves the shelf and belongs to the animation;
    # at dwell-end it belongs to the carrying robot, then to its destination.
    cartons = [s['cargo_id'] for s in warehouse.rack_slots if s['state'] == 'stored']
    for robot in fleet:
        if robot.current_task and (robot.carrying or robot.handling):
            cartons.append(robot.current_task['cargo_id'])
    assert len(cartons) == len(set(cartons)), f'Duplicate carton: {cartons}'
    assert set(cartons) == original, f'Lost/new inventory: {original ^ set(cartons)}'
    for task in manager.pending_tasks + manager.active_tasks:
        dest = warehouse.get_slot(task.dropoff_slot_id)
        assert dest['state'] == 'reserved' and dest['task_id'] == task.id


def run_episode(number):
    warehouse, manager, fleet, network = setup(number)
    mission = manager.consolidation
    original = {s['cargo_id'] for s in warehouse.stored_slots()}
    mission.start(fleet)
    assigned, picked, delivered = set(), set(), set()
    for tick in range(1, 2001):
        mission.refresh(fleet, tick)
        assignments = manager.allocate_tasks(fleet, network, tick=tick)
        assigned.update(a['task_id'] for a in assignments)
        for robot in fleet:
            action = robot.tick(tick, network)
            if robot.handling:
                payload = robot.current_task
                kind = robot.handling['kind']
                assert robot.handling['target'] == list(payload[f'{kind}_slot_cell'])
                assert (robot.x, robot.y) in warehouse.rack_access_cells(robot.handling['target'])
            if action == 'handling' and robot.handling['kind'] == 'pickup' and robot.handling['progress'] == 0:
                task_id = robot.handling['task_id']
                manager.note_pickup(task_id); picked.add(task_id)
            elif action == 'picked_up':
                manager.note_pickup(robot.current_task['id'])
            elif action == 'delivered':
                outcome, task = manager.complete_leg(robot.last_delivered_task_id)
                assert outcome == 'stored'
                delivered.add(task.id)
        mission.collisions += len(detect_collisions(fleet))
        deadlocks = detect_deadlock(fleet)
        if deadlocks:
            mission.deadlocks += len(deadlocks)
            resolve_deadlock(fleet, deadlocks, warehouse, network, tick)
        mission.refresh(fleet, tick)
        audit_inventory(warehouse, manager, fleet, original)
        if mission.status == 'completed':
            return warehouse, manager, fleet, tick, assigned, picked, delivered
    raise AssertionError(f'WH{number} did not complete: {mission.to_dict()}')


class ConsolidationTests(unittest.TestCase):
    def test_detect_empty_target_and_discover_stable_cartons(self):
        warehouse, manager, _, _ = setup()
        mission = manager.consolidation
        self.assertEqual(warehouse.consolidation['target_rack'], mission.detect_target()['code'])
        self.assertTrue(all(s['state'] == 'empty' for s in mission.target_slots()))
        self.assertEqual(len(warehouse.consolidation['initial_inventory']), len(mission.movable_cartons()))
        self.assertEqual(len(warehouse.rack_islands)-1, len({s['island'] for s in warehouse.stored_slots()}))

    def test_valid_lowest_cost_deterministic_tasks(self):
        warehouse, manager, fleet, _ = setup()
        mission = manager.consolidation
        candidates = [mission.route_pair(s,d,fleet)[0] for s in mission.movable_cartons() for d in mission.target_slots() if mission.route_pair(s,d,fleet)]
        mission.start(fleet)
        self.assertEqual(min(candidates), manager.all_tasks[0].estimated_cost)
        self.assertEqual(mission.capacity, len(manager.pending_tasks))
        pairs = [(t.cargo_id,t.pickup_slot_code,t.dropoff_slot_code) for t in manager.all_tasks]
        self.assertEqual(len(pairs),len({t.cargo_id for t in manager.all_tasks}))
        for t in manager.all_tasks:
            self.assertNotEqual(t.source_rack,t.destination_rack)
            self.assertEqual(t.cargo_id,warehouse.get_slot(t.pickup_slot_id)['cargo_id'])
            self.assertEqual('reserved',warehouse.get_slot(t.dropoff_slot_id)['state'])
        _, repeat, other_fleet, _ = setup();repeat.consolidation.start(other_fleet)
        self.assertEqual(pairs,[(t.cargo_id,t.pickup_slot_code,t.dropoff_slot_code) for t in repeat.all_tasks])

    def test_auction_is_existing_highest_bid_and_broadcast(self):
        _, manager, fleet, network = setup()
        manager.consolidation.start(fleet)
        task = manager.pending_tasks[0]
        bids = {r.id:r.calculate_bid(task.as_payload()) for r in fleet}
        winner = max(bids,key=lambda rid:(bids[rid],-rid))
        with patch.object(network,'broadcast',wraps=network.broadcast) as broadcast:
            assignments = manager.allocate_tasks(fleet,network,tick=1)
        self.assertEqual(winner, assignments[0]['robot_id'])
        self.assertTrue(any(call.args[1]=='result' for call in broadcast.call_args_list))

    def test_all_three_warehouses_end_to_end(self):
        for number in (1,2,3):
            with self.subTest(warehouse=number):
                warehouse, manager, fleet, tick, assigned, picked, delivered = run_episode(number)
                mission=manager.consolidation
                self.assertEqual(mission.capacity,len(delivered))
                self.assertEqual(assigned,picked);self.assertEqual(picked,delivered)
                self.assertTrue(all(s['state']=='stored' for s in mission.target_slots()))
                self.assertTrue(all(warehouse.get_slot(t.pickup_slot_id)['state']=='empty' for t in manager.completed_tasks))
                self.assertEqual(0, mission.collisions)
                self.assertTrue(mission.robots_used)
                print(f'WH{number}: {len(delivered)} relocations, tick {tick}, robots {sorted(mission.robots_used)}, collisions {mission.collisions}, deadlocks {mission.deadlocks}')

    def test_no_empty_target_and_already_full(self):
        warehouse,manager,fleet,_=setup()
        slot=manager.consolidation.target_slots()[0];slot.update(state='stored',cargo_id='unexpected')
        with self.assertRaisesRegex(ValueError,'No empty target'):
            manager.consolidation.start(fleet)
        for s in manager.consolidation.target_slots():s['state']='stored'
        with self.assertRaisesRegex(ValueError,'already full'):
            manager.consolidation.start(fleet)
        warehouse.consolidation=None
        with self.assertRaisesRegex(ValueError,'No consolidation target'):
            manager.consolidation.start(fleet)

    def test_insufficient_cartons_reports_partial(self):
        warehouse,manager,fleet,network=setup()
        for slot in manager.consolidation.movable_cartons()[1:]:warehouse.release_slot(slot['id'])
        manager.consolidation.start(fleet)
        task=manager.pending_tasks[0]
        manager.allocate_tasks(fleet,network)
        manager.note_pickup(task.id);manager.complete_leg(task.id)
        manager.consolidation.refresh(fleet)
        self.assertEqual('partial',manager.consolidation.status)
        self.assertIn('Insufficient',manager.consolidation.message)

    def test_no_robot_and_return_to_service(self):
        _,manager,fleet,network=setup()
        for r in fleet:r.set_available(False)
        manager.consolidation.start(fleet)
        self.assertEqual('waiting_for_robots',manager.consolidation.status)
        self.assertEqual([],manager.allocate_tasks(fleet,network))
        fleet[0].set_available(True);manager.consolidation.refresh(fleet)
        self.assertTrue(manager.allocate_tasks(fleet,network))

    def test_unreachable_sources_and_destination(self):
        warehouse,manager,fleet,_=setup()
        for source in manager.consolidation.movable_cartons():
            warehouse.blocked_cells.update(warehouse.rack_access_cells(source['cell']))
        manager.consolidation.start(fleet)
        self.assertEqual('failed',manager.consolidation.status)
        self.assertIn('unreachable',manager.consolidation.message)
        _,manager,fleet,_=setup()
        for dest in manager.consolidation.target_slots():
            manager.warehouse.blocked_cells.update(manager.warehouse.rack_access_cells(dest['cell']))
        manager.consolidation.start(fleet)
        self.assertEqual('failed',manager.consolidation.status)

    def test_cancellation_preserves_carton_releases_claims_and_replenishes(self):
        warehouse,manager,fleet,_=setup();manager.consolidation.start(fleet)
        task=manager.pending_tasks[0];cargo=task.cargo_id
        manager.cancel_task(task.id,fleet)
        source=warehouse.get_slot(task.pickup_slot_id)
        self.assertEqual('stored',source['state']);self.assertEqual(cargo,source['cargo_id'])
        self.assertIsNone(source['task_id']);self.assertEqual('empty',warehouse.get_slot(task.dropoff_slot_id)['state'])
        manager.consolidation.refresh(fleet)
        self.assertEqual(manager.consolidation.capacity,manager.remaining())
        self.assertFalse(any(t.cargo_id==cargo for t in manager.pending_tasks))

    def test_reservation_loss_fails_task_without_destroying_source(self):
        warehouse,manager,fleet,_=setup();manager.consolidation.start(fleet)
        task=manager.pending_tasks[0]
        warehouse.release_slot(task.dropoff_slot_id)
        manager.consolidation.refresh(fleet)
        self.assertEqual('failed',task.status)
        self.assertEqual('stored',warehouse.get_slot(task.pickup_slot_id)['state'])
        self.assertIn('Destination slot unavailable',task.failure_reason)

    def test_cannot_cancel_picked_up_carton_and_timeout_retains_state(self):
        warehouse,manager,fleet,network=setup();manager.consolidation.start(fleet)
        manager.allocate_tasks(fleet,network);task=manager.active_tasks[0]
        manager.note_pickup(task.id)
        with self.assertRaisesRegex(ValueError,'picked-up'):
            manager.cancel_task(task.id,fleet)
        manager.consolidation.timeout()
        self.assertEqual('timed_out',manager.consolidation.status)
        self.assertEqual('reserved',warehouse.get_slot(task.dropoff_slot_id)['state'])

    def test_unavailable_robot_reauctions_without_losing_claims(self):
        warehouse, manager, fleet, network = setup()
        manager.consolidation.start(fleet)
        manager.allocate_tasks(fleet[:1], network)
        task = manager.active_tasks[0]
        robot = next(r for r in fleet if r.id == task.assigned_to)
        robot.set_available(False)
        manager.handle_unavailable_robot(robot, fleet)
        self.assertEqual('pending', task.status)
        self.assertIsNone(task.assigned_to)
        self.assertEqual(task.id, warehouse.get_slot(task.pickup_slot_id)['task_id'])
        self.assertEqual(task.id, warehouse.get_slot(task.dropoff_slot_id)['task_id'])
        manager.allocate_tasks(fleet, network)
        self.assertEqual('assigned', task.status)
        self.assertNotEqual(robot.id, task.assigned_to)

    def test_active_reservation_loss_pauses_carried_transfer(self):
        warehouse, manager, fleet, network = setup()
        manager.consolidation.start(fleet)
        manager.allocate_tasks(fleet, network)
        task = manager.active_tasks[0]
        manager.note_pickup(task.id)
        warehouse.release_slot(task.dropoff_slot_id)
        manager.consolidation.refresh(fleet)
        self.assertEqual('blocked', manager.consolidation.status)
        self.assertIn('ownership retained', manager.consolidation.message)
        self.assertIn(task, manager.active_tasks)

    def test_target_comes_only_from_data_not_default_rack(self):
        warehouse, manager, fleet, _ = setup()
        target = warehouse.rack_islands[-1]
        warehouse.consolidation = {
            'target_rack': target['code'], 'capacity': 2,
            'initial_inventory': [
                {'slot': s['code'], 'cargo_id': f'ALT-{s["id"]}'}
                for s in warehouse.rack_slots if s['island'] != target['code']
            ],
        }
        manager.consolidation.prepare()
        manager.consolidation.start(fleet)
        self.assertEqual(2, manager.remaining())
        self.assertTrue(all(t.destination_rack == target['code'] for t in manager.all_tasks))

    def test_warehouse_configuration_validation_and_capacity(self):
        warehouse,manager,fleet,_=setup()
        warehouse.consolidation['initial_inventory'].append(warehouse.consolidation['initial_inventory'][0])
        before=[dict(s) for s in warehouse.rack_slots]
        with self.assertRaisesRegex(ValueError,'Duplicate'):manager.consolidation.prepare()
        self.assertEqual(before,warehouse.rack_slots)
        warehouse,manager,fleet,_=setup();warehouse.consolidation['capacity']=2
        manager.consolidation.prepare();manager.consolidation.start(fleet)
        self.assertEqual(2,len(manager.pending_tasks))
        warehouse.consolidation['capacity']=999
        with self.assertRaisesRegex(ValueError,'capacity'):manager.consolidation.detect_target()


if __name__=='__main__':unittest.main()
