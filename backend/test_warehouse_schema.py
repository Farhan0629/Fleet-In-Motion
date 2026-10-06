"""Unit tests for the standard Warehouse Definition Schema and parser."""
import json
import sys
import unittest
from pathlib import Path

# Ensure backend directory is in sys.path
sys.path.insert(0, str(Path(__file__).parent))

from pydantic import ValidationError

from warehouse import Warehouse, LAYOUT
from warehouse_schema import WarehouseDefinition, WarehouseDimensions, OperationalSettings


class WarehouseSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema_dir = Path(__file__).parent / "warehouses"
        self.warehouse_1_file = self.schema_dir / "warehouse_1.json"

    def test_warehouse_1_file_exists_and_loads(self):
        """Standard definition file for Warehouse #1 must exist and validate cleanly."""
        self.assertTrue(self.warehouse_1_file.exists())
        definition = WarehouseDefinition.from_file(self.warehouse_1_file)
        self.assertEqual(definition.id, "warehouse_1")
        self.assertEqual(definition.dimensions.width, 20)
        self.assertEqual(definition.dimensions.height, 20)
        self.assertEqual(len(definition.layout), 20)
        self.assertEqual(len(definition.stations), 12)
        self.assertEqual(len(definition.chargers), 4)

    def test_warehouse_instantiation_from_file(self):
        """Warehouse.from_file() must construct a fully functional runtime warehouse."""
        wh = Warehouse.from_file(self.warehouse_1_file)
        self.assertEqual(wh.width, 20)
        self.assertEqual(wh.height, 20)
        self.assertEqual(len(wh.tables), 12)
        self.assertEqual(len(wh.rack_islands), 9)
        self.assertEqual(len(wh.rack_slots), 36)
        self.assertEqual(len(wh.charging_stations), 4)
        self.assertEqual(wh.target_islands, [0, 4, 8])

    def test_round_trip_export_fidelity(self):
        """Exporting a Warehouse to schema dict and reloading it must preserve properties."""
        wh_original = Warehouse.from_file(self.warehouse_1_file)
        schema_dict = wh_original.to_schema_dict()
        wh_reloaded = Warehouse.from_dict(schema_dict)

        self.assertEqual(wh_reloaded.width, wh_original.width)
        self.assertEqual(wh_reloaded.height, wh_original.height)
        self.assertEqual(wh_reloaded.raw_layout, wh_original.raw_layout)
        self.assertEqual(len(wh_reloaded.tables), len(wh_original.tables))
        self.assertEqual(len(wh_reloaded.rack_slots), len(wh_original.rack_slots))
        self.assertEqual(len(wh_reloaded.rack_islands), len(wh_original.rack_islands))
        self.assertEqual(wh_reloaded.charging_stations, wh_original.charging_stations)

    def test_invalid_layout_character_rejected(self):
        """Layout with invalid cell characters must raise a ValidationError."""
        bad_layout = [
            "WWWW",
            "W.XW",  # 'X' is invalid
            "W..W",
            "WWWW",
        ]
        with self.assertRaises(ValidationError) as ctx:
            WarehouseDefinition(
                id="test_invalid_char",
                name="Invalid Character Test",
                dimensions=WarehouseDimensions(width=4, height=4),
                layout=bad_layout,
            )
        self.assertIn("Invalid cell character 'X'", str(ctx.exception))

    def test_mismatched_row_width_rejected(self):
        """Layout with row length different from dimensions.width must raise ValidationError."""
        bad_layout = [
            "WWWW",
            "W.",  # Only 2 chars instead of 4
            "W..W",
            "WWWW",
        ]
        with self.assertRaises(ValidationError) as ctx:
            WarehouseDefinition(
                id="test_mismatch_width",
                name="Mismatched Width Test",
                dimensions=WarehouseDimensions(width=4, height=4),
                layout=bad_layout,
            )
        self.assertIn("does not match dimensions.width", str(ctx.exception))

    def test_mismatched_height_rejected(self):
        """Layout with row count different from dimensions.height must raise ValidationError."""
        bad_layout = [
            "WWWW",
            "W..W",
            "W..W",
            "W..W",
            "WWWW",
        ]  # 5 rows instead of 4
        with self.assertRaises(ValidationError) as ctx:
            WarehouseDefinition(
                id="test_mismatch_height",
                name="Mismatched Height Test",
                dimensions=WarehouseDimensions(width=4, height=4),
                layout=bad_layout,
            )
        self.assertIn("does not match dimensions.height", str(ctx.exception))

    def test_json_schema_export_valid(self):
        """WarehouseDefinition.export_json_schema() must return a valid JSON schema."""
        schema = WarehouseDefinition.export_json_schema()
        self.assertEqual(schema["type"], "object")
        self.assertIn("properties", schema)
        self.assertIn("layout", schema["properties"])
        self.assertIn("dimensions", schema["properties"])


if __name__ == "__main__":
    unittest.main()
