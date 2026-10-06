"""Phase 5 validation for the automated cross-dock and ASRS warehouse."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from collision import detect_collisions, detect_deadlock, resolve_deadlock
from environment_engine import EnvironmentEngine
from p2p import P2PNetwork
from presentation_robot import PresentationRobot
from smoke_demo import audit_cartons
from task_manager import TaskManager


SCHEMA_DIR = Path(__file__).parent / "warehouses"


def count_swaps(robots) -> int:
    swaps = 0
    for index, first in enumerate(robots):
        first_previous = (getattr(first, "prev_x", first.x), getattr(first, "prev_y", first.y))
        first_now = (first.x, first.y)
        if first_now == first_previous:
            continue
        for second in robots[index + 1:]:
            second_previous = (getattr(second, "prev_x", second.x), getattr(second, "prev_y", second.y))
            second_now = (second.x, second.y)
            if second_now != second_previous and first_now == second_previous and second_now == first_previous:
                swaps += 1
    return swaps


def run_putaway_episode(seed: int = 0) -> dict:
    # The current algorithms are deterministic; seed is recorded now so Phase 9
    # can extend the same result shape without rewriting this Phase 5 baseline.
    warehouse, _ = EnvironmentEngine.compile_file(SCHEMA_DIR / "warehouse_3.json")
    tasks = TaskManager(warehouse)
    manifest = tasks.generate_manifest(storage=True)
    network = P2PNetwork()
    fleet = [
        PresentationRobot(index + 1, warehouse.robot_starts[index], warehouse, 100.0)
        for index in range(3)
    ]
    for robot in fleet:
        network.register_robot(robot.id)

    result = {
        "seed": seed,
        "tasks": len(manifest),
        "completion_tick": None,
        "same_cell_collisions": 0,
        "swap_collisions": 0,
        "deadlocks_resolved": 0,
        "replans": 0,
        "messages": 0,
        "solid_footprint_entries": 0,
    }
    asrs = next(zone for zone in warehouse.zones if zone["id"] == "asrs_core")
    min_x, min_y, max_x, max_y = asrs["metadata"]["navigation_footprint"]
    for tick in range(1, 1201):
        tasks.allocate_tasks(fleet, network, None, tick)
        for robot in fleet:
            previous_path_length = len(robot.planned_path)
            action = robot.tick(tick, network, None)
            if len(robot.planned_path) > 0 and robot.path_index == 1 and previous_path_length != len(robot.planned_path):
                result["replans"] += 1
            if action == "handling" and robot.handling and robot.handling["progress"] == 0 and robot.handling["kind"] == "pickup":
                tasks.note_pickup(robot.handling["task_id"])
            elif action == "picked_up" and robot.current_task:
                tasks.note_pickup(robot.current_task["id"])
            elif action == "delivered" and robot.last_delivered_task_id:
                tasks.complete_leg(robot.last_delivered_task_id)
            if min_x <= robot.x <= max_x and min_y <= robot.y <= max_y:
                result["solid_footprint_entries"] += 1

        result["same_cell_collisions"] += len(detect_collisions(fleet))
        result["swap_collisions"] += count_swaps(fleet)
        cycles = detect_deadlock(fleet)
        if cycles:
            result["deadlocks_resolved"] += len(cycles)
            resolve_deadlock(fleet, cycles, warehouse, network, tick)

        carton_errors = audit_cartons(warehouse, fleet, tasks)
        if carton_errors:
            raise AssertionError(f"Carton invariant failed at tick {tick}: {carton_errors}")
        if tasks.remaining() == 0:
            result["completion_tick"] = tick
            break

    result["messages"] = len(network.message_log)
    return result


class Warehouse3Tests(unittest.TestCase):
    def test_definition_compiles_as_distinct_connected_topology(self):
        warehouse, report = EnvironmentEngine.compile_file(SCHEMA_DIR / "warehouse_3.json")
        self.assertTrue(report.is_valid, report.summary())
        self.assertEqual(report.warehouse_id, "warehouse_3")
        self.assertEqual(report.dimensions, (36, 24))
        self.assertEqual(report.connected_components, 1)
        self.assertEqual(report.table_count, 12)
        self.assertEqual(report.charger_count, 8)
        self.assertEqual(report.rack_island_count, 8)
        self.assertEqual(report.rack_slot_count, 60)
        self.assertGreaterEqual(report.graph_diameter, 50)
        self.assertEqual(warehouse.theme, "automated_campus")
        self.assertEqual(len(warehouse.zones), 17)
        self.assertEqual(len(warehouse.exterior_assets), 24)

    def test_same_robot_class_initializes_in_all_three_warehouses(self):
        dimensions = []
        for warehouse_id in ("warehouse_1", "warehouse_2", "warehouse_3"):
            warehouse, report = EnvironmentEngine.compile_file(SCHEMA_DIR / f"{warehouse_id}.json")
            self.assertTrue(report.is_valid)
            robot = PresentationRobot(1, warehouse.robot_starts[0], warehouse, 100.0)
            self.assertIs(type(robot), PresentationRobot)
            self.assertTrue(warehouse.is_walkable(robot.x, robot.y))
            dimensions.append((warehouse.width, warehouse.height))
        self.assertEqual(dimensions, [(20, 20), (28, 16), (36, 24)])

    def test_putaway_targets_multiple_rack_topologies(self):
        warehouse, _ = EnvironmentEngine.compile_file(SCHEMA_DIR / "warehouse_3.json")
        tasks = TaskManager(warehouse)
        manifest = tasks.generate_manifest(storage=True)
        self.assertEqual(len(manifest), 12)
        targeted_islands = {task.slot_code.split("-")[0] for task in manifest}
        self.assertGreaterEqual(len(targeted_islands), 2)
        targeted_sizes = {
            island["size"]
            for island in warehouse.rack_islands
            if island["code"] in targeted_islands
        }
        self.assertEqual(targeted_sizes, {6, 8})
        for task in manifest:
            slot = warehouse.get_slot(task.slot_id)
            self.assertIn(tuple(task.destination), [tuple(item["cell"]) for item in warehouse.rack_slots])
            self.assertIn(tuple(task.dropoff), warehouse.rack_access_cells(slot["cell"]))

    def test_deterministic_three_episode_baseline(self):
        results = [run_putaway_episode(seed) for seed in (501, 502, 503)]
        print("\nPHASE 5 WAREHOUSE #3 BASELINE")
        for result in results:
            print(result)
        self.assertTrue(all(result["completion_tick"] is not None for result in results))
        self.assertTrue(all(result["same_cell_collisions"] == 0 for result in results))
        self.assertTrue(all(result["swap_collisions"] == 0 for result in results))
        self.assertTrue(all(result["solid_footprint_entries"] == 0 for result in results))
        self.assertTrue(all(result["tasks"] == 12 for result in results))


if __name__ == "__main__":
    unittest.main()