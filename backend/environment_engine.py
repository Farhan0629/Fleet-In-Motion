"""Warehouse Compiler and Environment Engine.

Parses declarative warehouse definitions, runs graph topology diagnostics,
verifies aisle connectivity, station accessibility, and fleet spawn validity,
and produces a validated runtime Warehouse environment.
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

from config import EMPTY, SHELF, WALL, PICKUP, DROPOFF, CHARGING
from warehouse import Warehouse
from warehouse_schema import WarehouseDefinition


class EnvironmentReport:
    """Detailed topological and operational diagnostics for a warehouse layout."""

    def __init__(self):
        self.is_valid: bool = True
        self.warehouse_id: str = ""
        self.name: str = ""
        self.dimensions: tuple[int, int] = (0, 0)
        self.total_cells: int = 0
        self.walkable_cells: int = 0
        self.shelf_cells: int = 0
        self.wall_cells: int = 0
        self.pickup_count: int = 0
        self.dropoff_count: int = 0
        self.charger_count: int = 0
        self.table_count: int = 0
        self.rack_island_count: int = 0
        self.rack_slot_count: int = 0
        self.connected_components: int = 0
        self.graph_diameter: int = 0
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "warehouse_id": self.warehouse_id,
            "name": self.name,
            "dimensions": {"width": self.dimensions[0], "height": self.dimensions[1]},
            "cell_counts": {
                "total": self.total_cells,
                "walkable": self.walkable_cells,
                "shelf": self.shelf_cells,
                "wall": self.wall_cells,
            },
            "facility_counts": {
                "pickups": self.pickup_count,
                "dropoffs": self.dropoff_count,
                "chargers": self.charger_count,
                "tables": self.table_count,
                "rack_islands": self.rack_island_count,
                "rack_slots": self.rack_slot_count,
            },
            "topology": {
                "connected_components": self.connected_components,
                "graph_diameter": self.graph_diameter,
            },
            "warnings": self.warnings,
            "errors": self.errors,
        }

    def summary(self) -> str:
        status = "PASSED" if self.is_valid else "FAILED"
        lines = [
            f"Environment Compilation [{status}]: {self.name} ({self.warehouse_id})",
            f"  Dimensions : {self.dimensions[0]}x{self.dimensions[1]} ({self.total_cells} cells)",
            f"  Walkability: {self.walkable_cells} walkable, {self.shelf_cells} shelves, {self.wall_cells} walls",
            f"  Stations   : {self.table_count} tables, {self.rack_slot_count} slots across {self.rack_island_count} islands, {self.charger_count} chargers",
            f"  Topology   : {self.connected_components} connected component(s), aisle graph diameter {self.graph_diameter} m",
        ]
        if self.warnings:
            lines.append(f"  Warnings ({len(self.warnings)}): " + "; ".join(self.warnings))
        if self.errors:
            lines.append(f"  Errors ({len(self.errors)}): " + "; ".join(self.errors))
        return "\n".join(lines)


class EnvironmentEngine:
    """Compiler and verifier for warehouse definitions."""

    @classmethod
    def compile_file(cls, path: str | Path) -> tuple[Warehouse, EnvironmentReport]:
        """Compile a warehouse from a JSON definition file."""
        definition = WarehouseDefinition.from_file(path)
        return cls.compile_definition(definition)

    @classmethod
    def compile_dict(cls, data: dict[str, Any]) -> tuple[Warehouse, EnvironmentReport]:
        """Compile a warehouse from a schema-compliant dictionary."""
        definition = WarehouseDefinition.model_validate(data)
        return cls.compile_definition(definition)

    @classmethod
    def compile_definition(cls, definition: WarehouseDefinition) -> tuple[Warehouse, EnvironmentReport]:
        """Verify layout topology and instantiate a runtime Warehouse instance."""
        report = EnvironmentReport()
        report.warehouse_id = definition.id
        report.name = definition.name
        report.dimensions = (definition.dimensions.width, definition.dimensions.height)
        report.total_cells = definition.dimensions.width * definition.dimensions.height

        # 1. Instantiate Warehouse runtime object
        warehouse = Warehouse.from_dict(definition.model_dump())

        # 2. Extract cell counts
        width, height = warehouse.width, warehouse.height
        walkable_cells: set[tuple[int, int]] = set()

        for y in range(height):
            for x in range(width):
                val = warehouse.grid[y][x]
                if val == SHELF:
                    report.shelf_cells += 1
                elif val == WALL:
                    report.wall_cells += 1
                else:
                    walkable_cells.add((x, y))

        report.walkable_cells = len(walkable_cells)
        report.pickup_count = len(warehouse.pickup_points)
        report.dropoff_count = len(warehouse.dropoff_points)
        report.charger_count = len(warehouse.charging_stations)
        report.table_count = len(warehouse.tables)
        report.rack_island_count = len(warehouse.rack_islands)
        report.rack_slot_count = len(warehouse.rack_slots)

        # 3. Verify Topology Connectivity using BFS
        if not walkable_cells:
            report.is_valid = False
            report.errors.append("Layout contains zero walkable cells.")
            return warehouse, report

        components = cls._analyze_connected_components(walkable_cells, width, height)
        report.connected_components = len(components)

        if len(components) > 1:
            report.is_valid = False
            isolated_sizes = [len(c) for c in components[1:]]
            report.errors.append(
                f"Floor contains {len(components)} disconnected walkable zones. "
                f"Main aisle has {len(components[0])} cells; {len(isolated_sizes)} disconnected pockets: {isolated_sizes} cells."
            )

        # 4. Compute Graph Diameter (longest shortest path on walkable floor)
        if components:
            report.graph_diameter = cls._compute_graph_diameter(components[0])

        # 5. Verify Accessibility of Stations
        cls._verify_station_access(warehouse, walkable_cells, report)

        # 6. Verify Accessibility of Rack Slots
        cls._verify_rack_slot_access(warehouse, walkable_cells, report)

        # 7. Verify Charging Station Accessibility & Capacity
        cls._verify_chargers(warehouse, walkable_cells, definition, report)

        # 8. Verify Robot Spawn Points
        cls._verify_spawn_points(warehouse, walkable_cells, definition, report)

        # 9. Physical presentation assets must agree with navigation. A semantic
        # zone may be larger than its machine, but every declared machine
        # footprint must be structural (wall/shelf), never a driveable aisle.
        cls._verify_navigation_footprints(warehouse, walkable_cells, report)

        # Attach report to warehouse instance
        setattr(warehouse, "environment_report", report)
        return warehouse, report

    @classmethod
    def _analyze_connected_components(
        cls, walkable_cells: set[tuple[int, int]], width: int, height: int
    ) -> list[set[tuple[int, int]]]:
        """Find all 4-connected components of walkable floor cells using BFS."""
        unvisited = set(walkable_cells)
        components: list[set[tuple[int, int]]] = []

        while unvisited:
            start = next(iter(unvisited))
            comp = set()
            queue = deque([start])
            comp.add(start)
            unvisited.remove(start)

            while queue:
                cx, cy = queue.popleft()
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if (nx, ny) in unvisited:
                        unvisited.remove((nx, ny))
                        comp.add((nx, ny))
                        queue.append((nx, ny))

            components.append(comp)

        # Sort largest first (main floor is index 0)
        components.sort(key=lambda c: len(c), reverse=True)
        return components

    @classmethod
    def _compute_graph_diameter(cls, component: set[tuple[int, int]]) -> int:
        """Calculate graph diameter using double-sweep BFS."""
        if not component:
            return 0

        def bfs_farthest(start_node):
            dist = {start_node: 0}
            queue = deque([start_node])
            farthest_node = start_node
            max_d = 0
            while queue:
                u = queue.popleft()
                d = dist[u]
                if d > max_d:
                    max_d = d
                    farthest_node = u
                for v in ((u[0] + 1, u[1]), (u[0] - 1, u[1]), (u[0], u[1] + 1), (u[0], u[1] - 1)):
                    if v in component and v not in dist:
                        dist[v] = d + 1
                        queue.append(v)
            return farthest_node, max_d

        start = next(iter(component))
        node_a, _ = bfs_farthest(start)
        _, diameter = bfs_farthest(node_a)
        return diameter

    @classmethod
    def _verify_station_access(
        cls, warehouse: Warehouse, walkable_cells: set[tuple[int, int]], report: EnvironmentReport
    ) -> None:
        """Check that every staging table cell is walkable or has a reachable neighbor."""
        for table in warehouse.tables:
            tx, ty = table["cell"]
            neighbors = [
                (tx + 1, ty), (tx - 1, ty), (tx, ty + 1), (tx, ty - 1)
            ]
            has_access = (tx, ty) in walkable_cells or any(n in walkable_cells for n in neighbors)
            if not has_access:
                report.is_valid = False
                report.errors.append(f"Staging table {table['code']} at ({tx},{ty}) is inaccessible (no walkable neighbors).")

    @classmethod
    def _verify_rack_slot_access(
        cls, warehouse: Warehouse, walkable_cells: set[tuple[int, int]], report: EnvironmentReport
    ) -> None:
        """Check that every rack slot has at least one valid aisle access cell."""
        for slot in warehouse.rack_slots:
            access = tuple(slot["access"])
            if access not in walkable_cells:
                report.is_valid = False
                report.errors.append(f"Rack slot {slot['code']} access cell {access} is not a walkable aisle.")

    @classmethod
    def _verify_chargers(
        cls,
        warehouse: Warehouse,
        walkable_cells: set[tuple[int, int]],
        definition: WarehouseDefinition,
        report: EnvironmentReport,
    ) -> None:
        """Check charging stations accessibility and fleet capacity."""
        if not warehouse.charging_stations:
            report.is_valid = False
            report.errors.append("Layout defines zero charging stations.")
            return

        for idx, (cx, cy) in enumerate(warehouse.charging_stations):
            if (cx, cy) not in walkable_cells:
                report.is_valid = False
                report.errors.append(f"Charging pad #{idx + 1} at ({cx},{cy}) is not on a walkable cell.")

        fleet_size = definition.operational_settings.default_num_robots
        if len(warehouse.charging_stations) < fleet_size:
            report.warnings.append(
                f"Charging capacity ({len(warehouse.charging_stations)} pads) is less than default fleet size ({fleet_size} AMRs)."
            )

    @classmethod
    def _verify_spawn_points(
        cls,
        warehouse: Warehouse,
        walkable_cells: set[tuple[int, int]],
        definition: WarehouseDefinition,
        report: EnvironmentReport,
    ) -> None:
        """Check that recommended robot spawn points land on valid walkable floor cells."""
        starts = definition.operational_settings.robot_starts
        seen_starts = set()
        for idx, (sx, sy) in enumerate(starts):
            if not (0 <= sx < warehouse.width and 0 <= sy < warehouse.height):
                report.is_valid = False
                report.errors.append(f"Robot start point #{idx + 1} ({sx},{sy}) is out of grid bounds.")
            elif (sx, sy) not in walkable_cells:
                report.is_valid = False
                report.errors.append(f"Robot start point #{idx + 1} ({sx},{sy}) is blocked or non-walkable.")
            if (sx, sy) in seen_starts:
                report.warnings.append(f"Duplicate robot start coordinate ({sx},{sy}).")
            seen_starts.add((sx, sy))

    @classmethod
    def _verify_navigation_footprints(
        cls, warehouse: Warehouse, walkable_cells: set[tuple[int, int]], report: EnvironmentReport
    ) -> None:
        """Validate optional solid-asset footprints declared by semantic zones."""
        for zone in getattr(warehouse, "zones", []):
            metadata = zone.get("metadata") or {}
            single = metadata.get("navigation_footprint")
            footprints = metadata.get("navigation_footprints")
            if single is not None and footprints is not None:
                report.is_valid = False
                report.errors.append(
                    f"Zone {zone.get('id', '<unknown>')} must use navigation_footprint or "
                    "navigation_footprints, not both."
                )
                continue
            if footprints is None:
                footprints = [single] if single is not None else []
            if not isinstance(footprints, (list, tuple)):
                report.is_valid = False
                report.errors.append(
                    f"Zone {zone.get('id', '<unknown>')} navigation_footprints must be a list of bounds."
                )
                continue
            for bounds in footprints:
                if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
                    report.is_valid = False
                    report.errors.append(
                        f"Zone {zone.get('id', '<unknown>')} navigation footprint must be "
                        "[min_x,min_y,max_x,max_y]."
                    )
                    continue
                min_x, min_y, max_x, max_y = (int(value) for value in bounds)
                if min_x > max_x or min_y > max_y or min_x < 0 or min_y < 0 or max_x >= warehouse.width or max_y >= warehouse.height:
                    report.is_valid = False
                    report.errors.append(
                        f"Zone {zone.get('id', '<unknown>')} navigation footprint {bounds} is outside the warehouse."
                    )
                    continue
                leaked = [
                    (x, y)
                    for y in range(min_y, max_y + 1)
                    for x in range(min_x, max_x + 1)
                    if (x, y) in walkable_cells
                ]
                if leaked:
                    report.is_valid = False
                    report.errors.append(
                        f"Zone {zone.get('id', '<unknown>')} solid navigation footprint overlaps "
                        f"{len(leaked)} walkable cell(s), including {leaked[:4]}."
                    )
