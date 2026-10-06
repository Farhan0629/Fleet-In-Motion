"""Barrier navigation regressions; run with python -m unittest test_barrier_navigation -v."""
import random
import unittest
from collections import deque
from config import EMPTY
from events import EventLogger
from p2p import P2PNetwork
from robot import Robot, PEER_MEMORY_TICKS
from presentation_robot import PresentationRobot
from warehouse import Warehouse


class BarrierNavigationTests(unittest.TestCase):
    def setUp(self):
        self.floor = Warehouse()
        self.robot = Robot(1, (3, 6), self.floor)
        self.net = P2PNetwork()
        self.net.register_robot(1)
        self.log = EventLogger()

    def assign(self, goal=(10, 6)):
        self.robot.assign_task({'id': 1, 'pickup': goal, 'dropoff': (16, 8)})

    def reach_pickup(self, max_ticks=100):
        for tick in range(1, max_ticks + 1):
            previous = (self.robot.x, self.robot.y)
            action = self.robot.tick(tick, self.net, self.log)
            current = (self.robot.x, self.robot.y)
            self.assertLessEqual(abs(current[0]-previous[0])+abs(current[1]-previous[1]), 1)
            self.assertTrue(self.floor.is_walkable(*current))
            if action == 'picked_up':
                return
        self.fail('Reachable pickup did not complete')

    def test_front_barrier_detours_without_warning(self):
        self.assign()
        self.floor.block_aisle(4, 6)
        self.robot.tick(1, self.net, self.log)
        self.assertNotEqual((self.robot.x, self.robot.y), (4, 6))
        self.assertIsNone(self.robot.navigation_message)
        self.reach_pickup()

    def test_partitioned_robot_replans_without_hazard_message(self):
        self.assign()
        self.net.partition_robot(1)
        self.floor.block_aisle(4, 6)
        self.reach_pickup()

    def test_u_shaped_barrier_requires_moving_away_from_goal(self):
        self.robot = Robot(1, (10, 7), self.floor)
        self.assign((16, 7))
        self.floor.blocked_cells.update({(x, 6) for x in range(9, 13)} |
                                        {(x, 8) for x in range(9, 13)} | {(12, 7)})
        self.robot.tick(1, self.net)
        self.assertEqual((self.robot.x, self.robot.y), (9, 7))
        self.reach_pickup()

    def test_closed_ring_warns_once_and_recovers_when_gap_opens(self):
        self.assign()
        self.floor.blocked_cells.update({(4, 6), (2, 6), (3, 5), (3, 7)})
        for tick in range(1, 5):
            self.assertEqual(self.robot.tick(tick, self.net, self.log), 'stuck')
        self.assertEqual(self.robot.to_dict()['navigation_message'], 'Please remove the barrier')
        warnings = [e for e in self.log.get_recent_events(30) if 'Please remove the barrier' in e['text']]
        self.assertEqual(len(warnings), 1)
        self.assertEqual((self.robot.x, self.robot.y), (3, 6))
        self.assertEqual(self.robot.current_task['id'], 1)
        self.floor.unblock_aisle(4, 6)
        self.robot.tick(5, self.net, self.log)
        self.assertIsNone(self.robot.navigation_message)
        self.reach_pickup()

    def test_larger_enclosure_detected_with_free_adjacent_cells(self):
        self.assign()
        self.floor.blocked_cells.update({(x, 4) for x in range(1, 5)} |
                                        {(x, 8) for x in range(1, 5)} |
                                        {(4, y) for y in range(4, 9)})
        self.assertTrue(self.floor.get_neighbors(3, 6))
        self.robot.tick(1, self.net)
        self.assertEqual(self.robot.navigation_message, 'Please remove the barrier')

    def test_goal_enclosed_warns_even_if_robot_has_space(self):
        self.assign()
        self.floor.blocked_cells.update({(11, 6), (9, 6), (10, 5), (10, 7)})
        self.robot.tick(1, self.net)
        self.assertEqual(self.robot.navigation_message, 'Please remove the barrier')

    def test_silent_peer_is_avoided_using_sensors(self):
        self.floor.set_occupancy(2, (4, 6))
        self.assign()
        self.assertNotIn((4, 6), self.robot.planned_path)
        self.net.partition_robot(1)
        self.reach_pickup()
        self.assertIsNone(self.robot.navigation_message)

    def test_stale_radio_position_cannot_block_sensor_confirmed_free_cell(self):
        self.robot.known_peer_positions[2] = (4, 6, 0)
        self.floor.set_occupancy(2, (3, 12))
        self.assign()
        self.robot.tick(1, self.net)
        self.assertEqual((self.robot.x, self.robot.y), (4, 6))

    def test_stale_position_and_intent_expire(self):
        self.robot.known_peer_positions[2] = (10, 6, 0)
        self.robot.known_peer_intents[2] = [(4, 6), (5, 6)]
        self.robot.known_peer_intent_ticks[2] = 0
        self.robot.known_peer_dists[2] = 1
        self.assign()
        self.robot.tick(PEER_MEMORY_TICKS+1, self.net)
        self.assertNotIn(2, self.robot.known_peer_positions)
        self.assertNotIn(2, self.robot.known_peer_intents)
        self.assertEqual((self.robot.x, self.robot.y), (4, 6))

    def test_intent_conflict_replans_to_safe_detour_after_bounded_wait(self):
        self.assign()
        self.robot.known_peer_intents[2] = [(4, 6), (5, 6)]
        self.robot.known_peer_dists[2] = 1
        for tick in range(1, 4):
            self.robot.known_peer_intent_ticks[2] = tick
            self.robot.tick(tick, self.net)
        self.assertNotEqual((self.robot.x, self.robot.y), (3, 6))
        self.assertNotEqual((self.robot.x, self.robot.y), (4, 6))
        self.assertIsNone(self.robot.navigation_message)

    def test_unreachable_building_location_is_not_blamed_on_barrier(self):
        self.floor.block_aisle(4, 6)
        self.assign((0, 0))
        self.robot.tick(1, self.net)
        self.assertEqual(self.robot.navigation_message, 'Destination unreachable')

    def test_temporary_traffic_is_not_a_barrier_warning(self):
        self.assign()
        for peer, cell in enumerate(self.floor.get_neighbors(3, 6), start=2):
            self.floor.set_occupancy(peer, cell)
        self.robot.tick(1, self.net)
        self.assertIsNone(self.robot.navigation_message)

    def test_carrying_robot_keeps_package_and_resumes_after_clear(self):
        self.assign()
        self.robot.carrying = True
        self.robot._replan_path()
        self.floor.blocked_cells.update(self.floor.get_neighbors(3, 6))
        self.robot.tick(1, self.net)
        self.assertTrue(self.robot.carrying)
        self.assertEqual(self.robot.current_task['id'], 1)
        self.floor.blocked_cells.clear()
        self.robot.tick(2, self.net)
        self.assertTrue(self.robot.carrying)
        self.assertIsNone(self.robot.navigation_message)
        self.assertEqual(self.robot.status, 'moving_to_dropoff')

    def test_charging_route_recovers_without_losing_pad(self):
        self.robot.target_charger = (1, 1)
        self.robot.status = 'moving_to_charge'
        self.robot._replan_path()
        self.floor.blocked_cells.update(self.floor.get_neighbors(3, 6))
        self.robot.tick(1, self.net)
        self.assertEqual(self.robot.navigation_message, 'Please remove the barrier')
        self.floor.blocked_cells.clear()
        self.robot.tick(2, self.net)
        self.assertEqual(self.robot.target_charger, (1, 1))
        self.assertEqual(self.robot.status, 'moving_to_charge')
        self.assertIsNone(self.robot.navigation_message)

    def test_idle_robot_surrounded_warns_and_clears(self):
        self.floor.blocked_cells.update(self.floor.get_neighbors(3, 6))
        self.robot.tick(1, self.net)
        self.assertEqual(self.robot.navigation_message, 'Please remove the barrier')
        self.floor.blocked_cells.clear()
        self.robot.tick(2, self.net)
        self.assertIsNone(self.robot.navigation_message)

    def test_presentation_robot_reroutes_and_completes_lift(self):
        self.robot = PresentationRobot(1, (3, 6), self.floor)
        self.assign()
        self.floor.block_aisle(4, 6)
        self.reach_pickup()
        self.assertTrue(self.robot.carrying)
        self.assertIsNone(self.robot.handling)

    def test_fleet_completes_storage_with_dynamic_barriers_and_radio_partition(self):
        from collision import detect_collisions, detect_deadlock, resolve_deadlock
        from config import DEFAULT_ROBOT_STARTS
        from pathfinding import a_star
        from task_manager import TaskManager
        floor, net = Warehouse(), P2PNetwork()
        tasks = TaskManager(floor)
        total = len(tasks.generate_manifest(storage=True))
        fleet = [PresentationRobot(i+1, DEFAULT_ROBOT_STARTS[i], floor) for i in range(3)]
        for unit in fleet:
            net.register_robot(unit.id)
        barriers_added = 0
        for tick in range(1, 1001):
            tasks.allocate_tasks(fleet, net, self.log, tick)
            if tick == 20:
                net.partition_robot(1)
            if 20 <= tick <= 100 and tick % 5 == 0 and barriers_added < 3:
                occupied = {(unit.x, unit.y) for unit in fleet}
                candidates = [cell for unit in fleet for cell in unit.planned_path[unit.path_index:]
                              if floor.grid[cell[1]][cell[0]] == EMPTY and cell not in occupied
                              and cell not in floor.blocked_cells]
                for cell in candidates:
                    floor.block_aisle(*cell)
                    goals = [(unit, unit.target_charger if not unit.current_task else
                              tuple(unit.current_task['dropoff' if unit.carrying else 'pickup']))
                             for unit in fleet if unit.current_task or unit.target_charger]
                    if all(a_star(floor, (unit.x, unit.y), goal) is not None for unit, goal in goals):
                        barriers_added += 1
                        break
                    floor.unblock_aisle(*cell)
            if tick == 100:
                net.restore_robot(1)
            for unit in fleet:
                action = unit.tick(tick, net, self.log)
                if (action == 'handling' and unit.handling['progress'] == 0
                        and unit.handling['kind'] == 'pickup'):
                    tasks.note_pickup(unit.handling['task_id'])
                elif action == 'picked_up' and unit.current_task:
                    tasks.note_pickup(unit.current_task['id'])
                elif action == 'delivered':
                    tasks.complete_leg(unit.last_delivered_task_id)
                self.assertNotEqual(unit.navigation_message, 'Please remove the barrier')
            self.assertFalse(detect_collisions(fleet))
            cycles = detect_deadlock(fleet)
            if cycles:
                resolve_deadlock(fleet, cycles, floor, net, tick)
            if len(tasks.completed_tasks) == total:
                break
        self.assertEqual(barriers_added, 3)
        self.assertEqual(len(tasks.completed_tasks), total)

    def test_deterministic_barrier_maps_agree_with_independent_bfs(self):
        candidates = [(x, y) for y in range(self.floor.height) for x in range(self.floor.width)
                      if self.floor.grid[y][x] == EMPTY and (x, y) not in {(3, 6), (10, 6)}]
        for seed in range(50):
            with self.subTest(seed=seed):
                self.floor.blocked_cells = set(random.Random(seed).sample(candidates, 70))
                self.robot = Robot(1, (3, 6), self.floor)
                goal = (10, 6)
                seen, queue = {(3, 6)}, deque([(3, 6)])
                while queue:
                    x, y = queue.popleft()
                    for cell in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
                        if self.floor.is_walkable(*cell) and cell not in seen:
                            seen.add(cell); queue.append(cell)
                self.assign(goal)
                if goal in seen:
                    self.assertIsNone(self.robot.navigation_message)
                    self.reach_pickup()
                else:
                    self.assertEqual(self.robot.navigation_message, 'Please remove the barrier')


if __name__ == '__main__':
    unittest.main()
