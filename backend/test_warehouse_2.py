"""Unit tests and empirical validation for Warehouse #2 (Isometric Smart Operations Hub)."""
import random
import sys
import unittest
from pathlib import Path

# Ensure backend directory is in sys.path
sys.path.insert(0, str(Path(__file__).parent))

from environment_engine import EnvironmentEngine
from warehouse import Warehouse
from robot import Robot
from presentation_robot import PresentationRobot
from p2p import P2PNetwork
from task_manager import TaskManager
from collision import detect_collisions, detect_deadlock, resolve_deadlock
from smoke_demo import audit_cartons


def count_swaps(robots) -> int:
    swaps = 0
    for index, first in enumerate(robots):
        first_prev = (getattr(first, "prev_x", first.x), getattr(first, "prev_y", first.y))
        first_now = (first.x, first.y)
        if first_now == first_prev:
            continue
        for second in robots[index + 1:]:
            second_prev = (getattr(second, "prev_x", second.x), getattr(second, "prev_y", second.y))
            second_now = (second.x, second.y)
            if second_now == second_prev:
                continue
            if first_now == second_prev and second_now == first_prev:
                swaps += 1
    return swaps


class Warehouse2Tests(unittest.TestCase):
    def setUp(self):
        self.schema_dir = Path(__file__).parent / "warehouses"
        self.warehouse_2_file = self.schema_dir / "warehouse_2.json"

    def test_warehouse_2_definition_and_compilation(self):
        """Warehouse #2 must compile cleanly with 100% connectivity and correct topology."""
        self.assertTrue(self.warehouse_2_file.exists())
        wh, report = EnvironmentEngine.compile_file(self.warehouse_2_file)
        self.assertTrue(report.is_valid)
        self.assertEqual(report.warehouse_id, "warehouse_2")
        self.assertEqual(report.dimensions, (28, 16))
        self.assertEqual(report.connected_components, 1)
        self.assertEqual(report.table_count, 12)
        self.assertEqual(report.charger_count, 8)
        self.assertGreaterEqual(report.rack_island_count, 8)
        self.assertGreater(report.graph_diameter, 25)
        self.assertEqual(len(report.errors), 0)

    def test_warehouse_2_central_chargers_accessible(self):
        """All 8 central power depot charging stations must be reachable by AMRs."""
        wh = Warehouse.from_file(self.warehouse_2_file)
        self.assertEqual(len(wh.charging_stations), 8)
        for pad in wh.charging_stations:
            self.assertTrue(wh.is_walkable(pad[0], pad[1]))
            neighbors = wh.get_neighbors(pad[0], pad[1])
            self.assertGreaterEqual(len(neighbors), 2)

    def test_warehouse_2_empirical_benchmark_report(self):
        """Execute deterministic multi-episode scenario on Warehouse #2 and report empirical metrics."""
        wh = Warehouse.from_file(self.warehouse_2_file)
        episodes = 5
        results = []

        total_same_cell = 0
        total_swaps = 0
        total_deadlocks = 0
        total_replans = 0
        completed_episodes = 0
        completion_ticks_list = []

        print("\n" + "=" * 65)
        print("EMPIRICAL BENCHMARK REPORT: WAREHOUSE #2 (Isometric Smart Hub)")
        print(f"Topology: {wh.width}x{wh.height} | Tables: {len(wh.tables)} | Chargers: {len(wh.charging_stations)}")
        print("=" * 65)

        for ep in range(episodes):
            p2p = P2PNetwork()
            tm = TaskManager(wh)
            manifest = tm.generate_manifest(storage=True)
            total_tasks = len(manifest)

            starts = wh.robot_starts[:3] if wh.robot_starts and len(wh.robot_starts) >= 3 else [(1, 1), (1, 6), (1, 13)]
            fleet = [PresentationRobot(i + 1, starts[i], wh, 100.0) for i in range(3)]
            for unit in fleet:
                p2p.register_robot(unit.id)

            ep_same_cell = 0
            ep_swaps = 0
            ep_deadlocks = 0
            ep_replans = 0
            stored = 0
            final_tick = None

            for tick in range(1, 500):
                tm.allocate_tasks(fleet, p2p, None, tick)
                for unit in fleet:
                    prev_plan_len = len(unit.planned_path)
                    action = unit.tick(tick, p2p, None)
                    if len(unit.planned_path) > 0 and unit.path_index == 1 and prev_plan_len != len(unit.planned_path):
                        ep_replans += 1

                    if action == "handling" and unit.handling and unit.handling["progress"] == 0 and unit.handling["kind"] == "pickup":
                        tm.note_pickup(unit.handling["task_id"])
                    elif action == "picked_up" and unit.current_task:
                        tm.note_pickup(unit.current_task["id"])
                    elif action == "delivered" and unit.last_delivered_task_id:
                        outcome, _ = tm.complete_leg(unit.last_delivered_task_id)
                        if outcome == "stored":
                            stored += 1

                ep_same_cell += len(detect_collisions(fleet))
                ep_swaps += count_swaps(fleet)

                cycles = detect_deadlock(fleet)
                if cycles:
                    ep_deadlocks += len(cycles)
                    resolve_deadlock(fleet, cycles, wh, p2p, tick)

                if stored >= total_tasks:
                    for unit in fleet:
                        unit.park_for_charging(p2p, tick)
                    if all(unit.parked for unit in fleet):
                        final_tick = tick
                        break

            if final_tick:
                completed_episodes += 1
                completion_ticks_list.append(final_tick)

            total_same_cell += ep_same_cell
            total_swaps += ep_swaps
            total_deadlocks += ep_deadlocks
            total_replans += ep_replans

            print(
                f"  Episode {ep + 1}/{episodes}: "
                f"Stored {stored}/{total_tasks} | "
                f"Ticks: {final_tick or 'TIMEOUT'} | "
                f"Collisions: {ep_same_cell} (same-cell) / {ep_swaps} (swap) | "
                f"Deadlocks resolved: {ep_deadlocks} | "
                f"Replans: {ep_replans}"
            )

        avg_ticks = sum(completion_ticks_list) / len(completion_ticks_list) if completion_ticks_list else 0.0
        completion_rate = (completed_episodes / episodes) * 100.0

        print("-" * 65)
        print("AGGREGATE EMPIRICAL SUMMARY:")
        print(f"  Completion Rate        : {completion_rate:.1f}% ({completed_episodes}/{episodes})")
        print(f"  Average Completion     : {avg_ticks:.1f} ticks")
        print(f"  Same-Cell Collisions   : {total_same_cell}")
        print(f"  Swap Collisions        : {total_swaps}")
        print(f"  Deadlocks Detected     : {total_deadlocks}")
        print(f"  Total Path Replans     : {total_replans}")
        print("=" * 65)

        self.assertEqual(total_same_cell, 0, f"Same-cell collisions detected on Warehouse #2: {total_same_cell}")
        self.assertEqual(total_swaps, 0, f"Swap collisions detected on Warehouse #2: {total_swaps}")
        self.assertEqual(completed_episodes, episodes, f"Not all episodes completed: {completed_episodes}/{episodes}")


if __name__ == "__main__":
    unittest.main()
