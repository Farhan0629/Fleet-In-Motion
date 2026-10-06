"""Isolated contract tests for handling dwell; not a full planner benchmark."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

class BaseRobot:
    def __init__(self, robot_id, start_pos, warehouse):
        self.id = robot_id
        self.x, self.y = start_pos
        self.current_task = {"id": 7, "pickup": start_pos, "dropoff": (17, 14)}
        self.carrying = False
        self.battery = 100
        self.completed = 0
    def _handle_arrival(self, tick, network):
        if not self.carrying:
            self.carrying = True
            self.status = 'moving_to_dropoff'
            return 'picked_up'
        self.carrying = False
        self.current_task = None
        self.completed += 1
        self.status = 'idle'
        return 'delivered'
    def _process_messages(self, *args): pass
    def _broadcast_position(self, *args): pass
    def _broadcast_intent(self, *args): pass
    def _go_to_charging(self, *args): self.current_task = None
    def to_dict(self): return {"has_cargo": self.carrying}
    def tick(self, tick, network, logger=None): return 'idle'

class Network:
    def __init__(self): self.messages = []
    def receive_all(self, robot_id): return []
    def broadcast(self, *args): self.messages.append(args)

spec = importlib.util.spec_from_file_location('_presentation_contract', Path(__file__).with_name('presentation_robot.py'))
module = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'robot': types.SimpleNamespace(Robot=BaseRobot), 'config': types.SimpleNamespace(BATTERY_DRAIN_IDLE=0.1)}):
    spec.loader.exec_module(module)

class HandlingContract(unittest.TestCase):
    def setUp(self):
        self.robot = module.PresentationRobot(1, (17, 5), None)
        self.net = Network()
    def test_pickup_changes_ownership_only_after_dwell(self):
        r = self.robot
        self.assertEqual(r._handle_arrival(10, self.net), 'handling')
        for tick in range(11, 20):
            self.assertEqual(r.tick(tick, self.net), 'handling')
            self.assertFalse(r.carrying)
        self.assertEqual(r.tick(20, self.net), 'picked_up')
        self.assertTrue(r.carrying)
        self.assertIsNone(r.handling)
    def test_delivery_is_reported_exactly_once(self):
        r = self.robot; r.carrying = True
        r._handle_arrival(10, self.net)
        self.assertEqual(r.tick(19, self.net), 'handling')
        self.assertEqual(r.completed, 0)
        self.assertEqual(r.tick(20, self.net), 'delivered')
        self.assertEqual(r.tick(21, self.net), 'idle')
        self.assertEqual(r.completed, 1)
    def test_no_tick_progress_means_no_transfer_progress(self):
        r = self.robot; r._handle_arrival(10, self.net)
        r.tick(15, self.net); first = r.to_dict()['handling']['progress']
        r.tick(15, self.net)
        self.assertEqual(r.to_dict()['handling']['progress'], first)
        self.assertEqual((r.x, r.y), (17, 5))
    def test_charging_does_not_abandon_a_transfer(self):
        r = self.robot; r._handle_arrival(10, self.net)
        r._go_to_charging(self.net, 11)
        self.assertEqual(r.current_task['id'], 7)
        self.assertTrue(all(message[2]['path'] == [] for message in self.net.messages))
    def test_reset_clears_handling(self):
        r = self.robot; r._handle_arrival(10, self.net)
        r.__init__(1, (1, 1), None)
        self.assertIsNone(r.handling)
    def test_rack_putaway_exposes_slot_and_facing(self):
        """The putaway leg animates against the slot, not the aisle cell."""
        r = self.robot
        r.carrying = True
        r.current_task = {"id": 9, "pickup": (2, 5), "dropoff": (17, 5),
                          "dropoff_kind": "rack", "slot_cell": (18, 5),
                          "slot_code": "C3-02", "stage": "putaway"}
        r._handle_arrival(10, self.net)
        handling = r.to_dict()['handling']
        self.assertEqual(handling['kind'], 'dropoff')
        self.assertEqual(handling['place'], 'rack')
        self.assertEqual(handling['stage'], 'putaway')
        self.assertEqual(handling['slot_code'], 'C3-02')
        self.assertEqual(handling['target'], [18, 5])
        self.assertEqual(handling['face'], 0)

    def test_table_handling_faces_the_declared_fixture_side(self):
        expected = {
            "north": ([17, 4], 270),
            "south": ([17, 6], 90),
            "west": ([16, 5], 180),
            "east": ([18, 5], 0),
        }
        for side, (target, face) in expected.items():
            with self.subTest(side=side):
                r = module.PresentationRobot(1, (17, 5), None)
                r.current_task["table_side"] = side
                r._handle_arrival(10, self.net)
                handling = r.to_dict()["handling"]
                self.assertEqual(handling["target"], target)
                self.assertEqual(handling["face"], face)

    def test_end_of_round_dock_waits_for_the_transfer(self):
        """The round finishing must not strand a carton in mid-air."""
        r = self.robot
        r._handle_arrival(10, self.net)
        self.assertFalse(r.park_for_charging(self.net, 11))
        self.assertEqual(r.current_task['id'], 7)
if __name__ == '__main__': unittest.main()
