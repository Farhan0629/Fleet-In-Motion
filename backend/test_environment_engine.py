"""Unit tests for EnvironmentEngine and topological compiler diagnostics."""
import sys
import unittest
from pathlib import Path

# Ensure backend directory is in sys.path
sys.path.insert(0, str(Path(__file__).parent))

from environment_engine import EnvironmentEngine, EnvironmentReport
from warehouse import Warehouse
from warehouse_schema import (
    WarehouseDefinition, WarehouseDimensions, OperationalSettings
)


class EnvironmentEngineTests(unittest.TestCase):
    def setUp(self):
        self.schema_dir = Path(__file__).parent / "warehouses"
        self.warehouse_1_file = self.schema_dir / "warehouse_1.json"

    def test_compile_warehouse_1_clean_pass(self):
        """Compiling standard Warehouse #1 must pass 100% of topological verifications."""
        warehouse, report = EnvironmentEngine.compile_file(self.warehouse_1_file)
        self.assertTrue(report.is_valid)
        self.assertEqual(len(report.errors), 0)
        self.assertEqual(report.connected_components, 1)
        self.assertGreater(report.walkable_cells, 200)
        self.assertEqual(report.table_count, 12)
        self.assertEqual(report.charger_count, 4)
        self.assertEqual(report.rack_island_count, 9)
        self.assertEqual(report.rack_slot_count, 36)
        self.assertGreater(report.graph_diameter, 20)
        self.assertIn("Environment Compilation [PASSED]", report.summary())

    def test_detects_disconnected_floor_zones(self):
        """Compiler must flag an error if a wall cuts the floor into disconnected pockets."""
        # A 6x6 floor split by a solid wall of 'W' at column 3
        disconnected_layout = [
            "WWWWWW",
            "W.W..W",
            "W.W..W",
            "W.W..W",
            "W.W..W",
            "WWWWWW",
        ]
        definition = WarehouseDefinition(
            id="disconnected_floor",
            name="Disconnected Floor Test",
            dimensions=WarehouseDimensions(width=6, height=6),
            layout=disconnected_layout,
            operational_settings=OperationalSettings(
                default_num_robots=1,
                robot_starts=[(1, 1)]
            )
        )
        warehouse, report = EnvironmentEngine.compile_definition(definition)
        self.assertFalse(report.is_valid)
        self.assertEqual(report.connected_components, 2)
        self.assertTrue(any("disconnected walkable zones" in err for err in report.errors))

    def test_detects_inaccessible_charger(self):
        """Compiler must flag charging pads that are placed on non-walkable or walled-off cells."""
        # Charger 'C' surrounded by walls
        walled_charger_layout = [
            "WWWWWW",
            "W....W",
            "W.WWWW",
            "W.WCWW",
            "W..WWW",
            "WWWWWW",
        ]
        definition = WarehouseDefinition(
            id="walled_charger",
            name="Walled Charger Test",
            dimensions=WarehouseDimensions(width=6, height=6),
            layout=walled_charger_layout,
            operational_settings=OperationalSettings(
                default_num_robots=1,
                robot_starts=[(1, 1)]
            )
        )
        warehouse, report = EnvironmentEngine.compile_definition(definition)
        # Charging pad is in an isolated component
        self.assertFalse(report.is_valid)
        self.assertTrue(any("disconnected" in err or "inaccessible" in err for err in report.errors))

    def test_detects_invalid_robot_spawns(self):
        """Compiler must reject robot spawn coordinates placed on walls or shelves."""
        layout = [
            "WWWWWW",
            "W....W",
            "W.##.W",
            "W.##.W",
            "WC...W",
            "WWWWWW",
        ]
        definition = WarehouseDefinition(
            id="invalid_spawn",
            name="Invalid Spawn Test",
            dimensions=WarehouseDimensions(width=6, height=6),
            layout=layout,
            operational_settings=OperationalSettings(
                default_num_robots=2,
                robot_starts=[
                    (1, 1),   # Valid walkable
                    (2, 2),   # Invalid: lands on a SHELF '#'
                ]
            )
        )
        warehouse, report = EnvironmentEngine.compile_definition(definition)
        self.assertFalse(report.is_valid)
        self.assertTrue(any("blocked or non-walkable" in err for err in report.errors))

    def test_warehouse_compile_from_file_integration(self):
        """Warehouse.compile_from_file() must succeed and attach environment_report."""
        wh = Warehouse.compile_from_file(self.warehouse_1_file)
        self.assertTrue(hasattr(wh, "environment_report"))
        self.assertTrue(wh.environment_report.is_valid)
        self.assertEqual(wh.environment_report.warehouse_id, "warehouse_1")

    def test_solid_zone_navigation_footprint_cannot_overlap_an_aisle(self):
        definition = WarehouseDefinition(
            id="footprint_overlap",
            name="Footprint overlap test",
            dimensions=WarehouseDimensions(width=6, height=6),
            layout=[
                "WWWWWW",
                "WC...W",
                "W....W",
                "W....W",
                "W...PW",
                "WWWWWW",
            ],
            operational_settings=OperationalSettings(
                default_num_robots=1,
                robot_starts=[(2, 2)],
            ),
            zones=[{
                "id": "machine",
                "name": "Machine",
                "category": "auxiliary",
                "bounds": (1, 1, 4, 4),
                "metadata": {"navigation_footprint": [2, 2, 3, 3]},
            }],
        )
        _, report = EnvironmentEngine.compile_definition(definition)
        self.assertFalse(report.is_valid)
        self.assertTrue(any("solid navigation footprint overlaps" in error for error in report.errors))

    def test_multi_part_solid_footprint_cannot_overlap_an_aisle(self):
        definition = WarehouseDefinition(
            id="multi_footprint_overlap",
            name="Multi footprint overlap test",
            dimensions=WarehouseDimensions(width=6, height=6),
            layout=[
                "WWWWWW",
                "WC...W",
                "W....W",
                "W....W",
                "W...PW",
                "WWWWWW",
            ],
            operational_settings=OperationalSettings(
                default_num_robots=1,
                robot_starts=[(2, 2)],
            ),
            zones=[{
                "id": "u_conveyor",
                "name": "U conveyor",
                "category": "sortation",
                "bounds": (1, 1, 4, 4),
                "metadata": {
                    "navigation_footprints": [
                        [1, 1, 1, 4],
                        [4, 1, 4, 4],
                        [2, 4, 3, 4],
                    ]
                },
            }],
        )
        _, report = EnvironmentEngine.compile_definition(definition)
        self.assertFalse(report.is_valid)
        self.assertTrue(any("solid navigation footprint overlaps" in error for error in report.errors))


if __name__ == "__main__":
    unittest.main()
