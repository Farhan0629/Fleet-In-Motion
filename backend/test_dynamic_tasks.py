"""Phase 6 task lifecycle tests.

These tests exercise semantic resolution and the existing bid auction directly,
without relying on the dashboard or warehouse-specific coordinates.
"""
from pathlib import Path
import unittest

from p2p import P2PNetwork
from robot import Robot
from task_manager import TaskManager
from warehouse import Warehouse


WAREHOUSES = Path(__file__).parent / "warehouses"


class DynamicTaskLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.warehouse = Warehouse.compile_from_file(WAREHOUSES / "warehouse_2.json")
        self.manager = TaskManager(self.warehouse)

    def test_create_prioritize_cancel_retry_and_complete(self):
        normal = self.manager.create_dynamic_task(
            "T01", "rack_a", priority=2, tick=10, max_retries=2
        )
        urgent = self.manager.create_dynamic_task(
            "T02", "packing_area", priority=5, tick=11
        )
        self.assertEqual([urgent.id, normal.id], [task.id for task in self.manager.pending_tasks])
        self.assertEqual("reserved", self.warehouse.get_slot(normal.dropoff_slot_id)["state"])

        self.manager.cancel_task(normal.id, [])
        self.assertEqual("cancelled", normal.status)
        self.assertEqual("empty", self.warehouse.get_slot(normal.dropoff_slot_id)["state"])

        self.manager.retry_task(normal.id)
        self.assertEqual("pending", normal.status)
        self.assertEqual(1, normal.retry_count)
        self.assertEqual("reserved", self.warehouse.get_slot(normal.dropoff_slot_id)["state"])

        self.assertTrue(self.manager.note_pickup(normal.id))
        normal.status = "assigned"
        self.manager.pending_tasks.remove(normal)
        self.manager.active_tasks.append(normal)
        outcome, _ = self.manager.complete_leg(normal.id)
        self.assertEqual("stored", outcome)
        self.assertEqual("stored", self.warehouse.get_slot(normal.dropoff_slot_id)["state"])

    def test_unavailable_robot_returns_uncollected_task_to_auction(self):
        task = self.manager.create_dynamic_task("T01", "packing_area")
        robot = Robot(1, self.warehouse.robot_starts[0], self.warehouse)
        network = P2PNetwork()
        network.register_robot(robot.id)
        self.manager.allocate_tasks([robot], network, tick=1)
        self.assertEqual("assigned", task.status)

        robot.set_available(False, "maintenance")
        self.manager.handle_unavailable_robot(robot, [robot])
        self.assertEqual("pending", task.status)
        self.assertIsNone(task.assigned_to)
        self.assertIsNone(robot.current_task)
        self.assertEqual(0.0, robot.calculate_bid(task.as_payload()))

    def test_stored_rack_can_be_a_semantic_pickup(self):
        zone = next(zone for zone in self.warehouse.zones if zone["id"] == "rack_a")
        min_x, min_y, max_x, max_y = zone["bounds"]
        slot = next(
            slot for slot in self.warehouse.rack_slots
            if min_x <= slot["cell"][0] <= max_x and min_y <= slot["cell"][1] <= max_y
        )
        slot["state"] = "stored"
        task = self.manager.create_dynamic_task("rack_a", "packing_area")
        self.assertEqual("rack", task.pickup_kind)
        self.assertEqual(slot["id"], task.pickup_slot_id)
        self.assertEqual(task.id, slot["task_id"])
        self.assertTrue(self.manager.note_pickup(task.id))
        self.assertEqual("empty", slot["state"])

    def test_destination_can_change_while_pending(self):
        task = self.manager.create_dynamic_task("T01", "packing_area")
        self.manager.update_destination(task.id, "dispatch_zone")
        self.assertEqual("dispatch_zone", task.destination_ref)
        self.assertEqual("DISPATCH ZONE", task.destination_label)

    def test_semantic_tasks_use_the_same_manager_in_all_warehouses(self):
        examples = {
            "warehouse_1": ("T01", "T07"),
            "warehouse_2": ("T01", "packing_area"),
            "warehouse_3": ("IN-01", "OUT-01"),
        }
        for warehouse_id, (source, destination) in examples.items():
            with self.subTest(warehouse=warehouse_id):
                warehouse = Warehouse.compile_from_file(WAREHOUSES / f"{warehouse_id}.json")
                manager = TaskManager(warehouse)
                task = manager.create_dynamic_task(source, destination)
                self.assertEqual(source, task.source_ref)
                self.assertEqual(destination, task.destination_ref)
                self.assertTrue(warehouse.is_walkable(*task.pickup))
                self.assertTrue(warehouse.is_walkable(*task.dropoff))


if __name__ == "__main__":
    unittest.main()