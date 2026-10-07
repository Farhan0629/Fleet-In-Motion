from config import (
    GRID_WIDTH, GRID_HEIGHT, EMPTY, SHELF, WALL, PICKUP, DROPOFF, CHARGING
)

# Fixed demonstration floor.
# Twelve staging tables: six on the WEST aisle (column 2) and six on the EAST
# aisle (column 16). In a storage round every one of them starts with a carton
# on it and the fleet works the whole floor. Rack islands are 2x2 blocks that
# force real aisle navigation.
# The two cell types (P/D) are kept because the headless benchmark still runs
# the original west-to-east delivery manifest for its baseline comparison.
LAYOUT = [
    "WWWWWWWWWWWWWWWWWWWW",  # 0
    "WC................CW",  # 1  chargers at (1,1) and (18,1)
    "W.P.............D..W",  # 2  load 1 / drop 1
    "W....##..##..##....W",  # 3
    "W....##..##..##....W",  # 4
    "W.P.............D..W",  # 5  load 2 / drop 2
    "W..................W",  # 6
    "W..................W",  # 7
    "W.P.............D..W",  # 8  load 3 / drop 3
    "W....##..##..##....W",  # 9
    "W....##..##..##....W",  # 10
    "W.P.............D..W",  # 11 load 4 / drop 4
    "W..................W",  # 12
    "W..................W",  # 13
    "W.P.............D..W",  # 14 load 5 / drop 5
    "W....##..##..##....W",  # 15
    "W....##..##..##....W",  # 16
    "W.P.............D..W",  # 17 load 6 / drop 6
    "WC................CW",  # 18 chargers at (1,18) and (18,18)
    "WWWWWWWWWWWWWWWWWWWW",  # 19
]

CHAR_TO_CELL = {
    ".": EMPTY,
    "#": SHELF,
    "W": WALL,
    "P": PICKUP,
    "D": DROPOFF,
    "C": CHARGING,
}

# Island rows are labelled A/B/C from north to south, columns 1..3 from west to
# east, so a slot address reads like a real warehouse location: B2-03.
RACK_BANDS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class Warehouse:
    """Warehouse grid map: neighbor lookup, walkability, and special cells."""

    def __init__(
        self,
        layout: list[str] | None = None,
        width: int | None = None,
        height: int | None = None,
        target_islands: list[int] | None = None,
        robot_starts: list[tuple[int, int]] | None = None,
        num_robots: int | None = None,
        warehouse_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
        theme: str | None = None,
        stations: list[dict] | None = None,
        zones: list[dict] | None = None,
        markings: list[dict] | None = None,
        exterior_assets: list[dict] | None = None,
        consolidation: dict | None = None,
    ):
        if layout is None:
            layout = LAYOUT
        self.raw_layout = layout
        self.height = height if height is not None else len(layout)
        self.width = width if width is not None else (len(layout[0]) if self.height > 0 else 0)
        self.warehouse_id = warehouse_id or "warehouse_default"
        self.name = name or "Warehouse"
        self.description = description or ""
        self.theme = theme or "classic_daylight"
        self.semantic_stations = stations or []
        self.zones = zones or []
        self.markings = markings or []
        self.exterior_assets = exterior_assets or []
        self.consolidation = consolidation
        self.target_islands = target_islands
        self.robot_starts = robot_starts
        self.num_robots = num_robots
        self.grid = self._build_grid(layout)
        self.pickup_points = []
        self.dropoff_points = []
        self.charging_stations = []
        self._extract_special_cells()
        # Staging tables, addressed T01..Tnn (west first, north to
        # south). A table is either "loaded" (one carton sitting on it) or
        # "empty". It is emptied the moment a unit starts lifting and is never
        # refilled during a round, so a carton can never reappear on a table it
        # has already left.
        self.tables: list[dict] = []
        self.blocked_cells = set()
        # Rack islands are real inventory locations, not scenery: every shelf
        # cell with an adjacent aisle is an addressable slot that can hold one
        # carton.
        self.rack_slots: list[dict] = []
        self.rack_islands: list[dict] = []
        self._extract_rack_slots()
        self._extract_tables()
        # Physical floor occupancy, written by robots as they move. This stands
        # in for onboard proximity sensing: a robot can see a body in the next
        # cell even when its radio is down, exactly like a real LiDAR bumper.
        self.robot_occupancy: dict[int, tuple[int, int]] = {}

    @classmethod
    def from_dict(cls, data: dict) -> "Warehouse":
        """Create a validated Warehouse instance from a dictionary matching the schema."""
        from warehouse_schema import WarehouseDefinition
        definition = WarehouseDefinition.model_validate(data)
        return cls(
            layout=definition.layout,
            width=definition.dimensions.width,
            height=definition.dimensions.height,
            consolidation=(definition.operational_settings.consolidation.model_dump()
                           if definition.operational_settings.consolidation else None),
            target_islands=definition.operational_settings.target_islands,
            robot_starts=definition.operational_settings.robot_starts,
            num_robots=definition.operational_settings.default_num_robots,
            warehouse_id=definition.id,
            name=definition.name,
            description=definition.description,
            theme=definition.theme,
            stations=[s.model_dump() for s in definition.stations],
            zones=[z.model_dump() for z in definition.zones],
            markings=[m.model_dump() for m in definition.markings],
            exterior_assets=[a.model_dump() for a in definition.exterior_assets],
        )

    @classmethod
    def compile_from_file(cls, path) -> "Warehouse":
        """Compile and verify a warehouse definition using the EnvironmentEngine."""
        from environment_engine import EnvironmentEngine
        wh, report = EnvironmentEngine.compile_file(path)
        if not report.is_valid:
            raise ValueError(f"Warehouse topology validation failed:\n{report.summary()}")
        return wh

    @classmethod
    def from_file(cls, path) -> "Warehouse":
        """Create a validated Warehouse instance from a warehouse JSON file."""
        from warehouse_schema import WarehouseDefinition
        definition = WarehouseDefinition.from_file(path)
        return cls(
            layout=definition.layout,
            width=definition.dimensions.width,
            height=definition.dimensions.height,
            consolidation=(definition.operational_settings.consolidation.model_dump()
                           if definition.operational_settings.consolidation else None),
            target_islands=definition.operational_settings.target_islands,
            robot_starts=definition.operational_settings.robot_starts,
            num_robots=definition.operational_settings.default_num_robots,
            warehouse_id=definition.id,
            name=definition.name,
            description=definition.description,
            theme=definition.theme,
            stations=[s.model_dump() for s in definition.stations],
            zones=[z.model_dump() for z in definition.zones],
            markings=[m.model_dump() for m in definition.markings],
            exterior_assets=[a.model_dump() for a in definition.exterior_assets],
        )

    def to_schema_dict(self) -> dict:
        """Export this Warehouse instance as a dictionary compliant with the schema."""
        from warehouse_schema import (
            WarehouseDefinition, WarehouseDimensions, OperationalSettings,
            StationDefinition, ChargerDefinition
        )
        return WarehouseDefinition(
            id=getattr(self, "warehouse_id", "warehouse_exported"),
            name=getattr(self, "name", "Exported Warehouse"),
            dimensions=WarehouseDimensions(width=self.width, height=self.height, cell_size=1.0),
            layout=self.raw_layout,
            operational_settings=OperationalSettings(
                consolidation=self.consolidation,
                target_islands=getattr(self, "target_islands", None),
                default_num_robots=getattr(self, "num_robots", 3),
                robot_starts=getattr(self, "robot_starts", []) or [],
            ),
            stations=[
                StationDefinition(id=t["id"], code=t["code"], cell=t["cell"], side=t["side"], station_type="table")
                for t in self.tables
            ],
            chargers=[
                ChargerDefinition(id=i, code=f"CHARGE {i+1}", cell=cell)
                for i, cell in enumerate(self.charging_stations)
            ],
        ).model_dump()

    def _build_grid(self, layout: list[str]) -> list[list[int]]:
        grid = []
        for row_str in layout:
            grid.append([CHAR_TO_CELL.get(ch, EMPTY) for ch in row_str])
        return grid

    def _extract_special_cells(self):
        # Sorted north-to-south so loading table N pairs with a delivery table.
        for y in range(self.height):
            for x in range(self.width):
                val = self.grid[y][x]
                if val == PICKUP:
                    self.pickup_points.append((x, y))
                elif val == DROPOFF:
                    self.dropoff_points.append((x, y))
                elif val == CHARGING:
                    self.charging_stations.append((x, y))

    # ─── Staging tables ───────────────────────────────────────────────────

    def _extract_tables(self):
        """Address every table while preserving its data-defined service side."""
        west = sorted(self.pickup_points, key=lambda cell: (cell[1], cell[0]))
        east = sorted(self.dropoff_points, key=lambda cell: (cell[1], cell[0]))
        station_by_cell = {
            tuple(station["cell"]): station
            for station in self.semantic_stations
        }
        for index, cell in enumerate(west + east):
            is_west = index < len(west) if (west and east) else (cell[0] < self.width / 2)
            station = station_by_cell.get(tuple(cell))
            self.tables.append({
                "id": index,
                "code": f"T{index + 1:02d}",
                "cell": cell,
                "side": station.get("side") if station else ("west" if is_west else "east"),
                "state": "empty",   # "empty" | "loaded"
                "task_id": None,
            })

    def table_at(self, cell) -> dict | None:
        cell = tuple(cell)
        for table in self.tables:
            if table["cell"] == cell:
                return table
        return None

    def semantic_locations(self) -> list[dict]:
        """Task-facing locations exposed by warehouse data, not UI coordinates."""
        locations = [
            {
                "id": station["code"],
                "label": station["code"],
                "kind": "station",
                "category": station.get("station_type", "table"),
            }
            for station in self.semantic_stations
        ]
        locations.extend({
            "id": zone["id"],
            "label": zone["name"],
            "kind": "zone",
            "category": zone["category"],
        } for zone in self.zones if zone["category"] != "restricted")
        return locations

    def resolve_semantic_location(self, reference: str, role: str) -> dict:
        """Resolve a station/zone name to a real navigation endpoint.

        Storage zones resolve to a physical rack slot. Other zones resolve to
        the closest walkable cell to their centre. This keeps TaskManager free
        of warehouse-specific coordinates.
        """
        key = str(reference or "").strip().lower()
        if not key:
            raise ValueError("Semantic location is required")
        for station in self.semantic_stations:
            if key in {str(station.get("id", "")).lower(), station["code"].lower()}:
                cell = tuple(station["cell"])
                if not self._structurally_walkable(*cell):
                    raise ValueError(f"Station {station['code']} is not walkable")
                table = self.table_at(cell)
                return {
                    "reference": station["code"],
                    "label": station["code"],
                    "cell": cell,
                    "kind": "table" if table else "station",
                    "side": station.get("side"),
                    "table": table,
                    "slot": None,
                }
        for zone in self.zones:
            if key not in {zone["id"].lower(), zone["name"].lower()}:
                continue
            min_x, min_y, max_x, max_y = zone["bounds"]
            if zone["category"] == "storage":
                candidates = [
                    slot for slot in self.rack_slots
                    if min_x <= slot["cell"][0] <= max_x and min_y <= slot["cell"][1] <= max_y
                    and (
                        (slot["state"] == "stored" and slot["task_id"] is None)
                        if role == "pickup" else slot["state"] == "empty"
                    )
                ]
                if not candidates:
                    raise ValueError(f"No {'stored' if role == 'pickup' else 'empty'} rack slot is available in {zone['name']}")
                center = ((min_x + max_x) / 2, (min_y + max_y) / 2)
                slot = min(candidates, key=lambda item: (
                    abs(item["cell"][0] - center[0]) + abs(item["cell"][1] - center[1]),
                    item["id"],
                ))
                return {
                    "reference": zone["id"],
                    "label": zone["name"],
                    "cell": tuple(slot["access"]),
                    "kind": "rack",
                    "side": None,
                    "table": None,
                    "slot": slot,
                }
            center = ((min_x + max_x) / 2, (min_y + max_y) / 2)
            candidates = [
                (x, y)
                for y in range(min_y, max_y + 1)
                for x in range(min_x, max_x + 1)
                if self.is_walkable(x, y)
            ]
            if not candidates:
                raise ValueError(f"Zone {zone['name']} has no walkable task endpoint")
            cell = min(candidates, key=lambda item: (
                abs(item[0] - center[0]) + abs(item[1] - center[1]),
                item[1], item[0],
            ))
            return {
                "reference": zone["id"],
                "label": zone["name"],
                "cell": cell,
                "kind": "zone",
                "side": None,
                "table": self.table_at(cell),
                "slot": None,
            }
        raise ValueError(f"Unknown semantic location: {reference}")

    def load_table(self, cell, task_id: int) -> bool:
        """Place the staged carton for `task_id` on the table at `cell`."""
        table = self.table_at(cell)
        if table is None:
            return False
        table["state"] = "loaded"
        table["task_id"] = task_id
        return True

    def mark_table_empty(self, cell) -> bool:
        """The carton has physically left the table - a unit is lifting it."""
        table = self.table_at(cell)
        if table is None or table["state"] == "empty":
            return False
        table["state"] = "empty"
        table["task_id"] = None
        return True

    def reset_tables(self):
        for table in self.tables:
            table["state"] = "empty"
            table["task_id"] = None

    def loaded_tables(self) -> list[dict]:
        return [table for table in self.tables if table["state"] == "loaded"]

    # ─── Rack inventory ───────────────────────────────────────────────────

    def _structurally_walkable(self, x: int, y: int) -> bool:
        """Walkable ignoring temporary barriers.

        A slot address is a property of the building, so a barrier dropped in
        an aisle during a drill must not delete the address; it only makes the
        route to it longer.
        """
        return (
            0 <= x < self.width
            and 0 <= y < self.height
            and self.grid[y][x] not in (SHELF, WALL)
        )

    def _extract_rack_slots(self):
        """Turn every contiguous shelf block into an addressable rack island."""
        seen: set[tuple[int, int]] = set()
        blocks: list[list[tuple[int, int]]] = []
        for y in range(self.height):
            for x in range(self.width):
                if self.grid[y][x] != SHELF or (x, y) in seen:
                    continue
                block: list[tuple[int, int]] = []
                stack = [(x, y)]
                while stack:
                    cx, cy = stack.pop()
                    if (cx, cy) in seen:
                        continue
                    if not (0 <= cx < self.width and 0 <= cy < self.height):
                        continue
                    if self.grid[cy][cx] != SHELF:
                        continue
                    seen.add((cx, cy))
                    block.append((cx, cy))
                    stack.extend([(cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)])
                blocks.append(sorted(block, key=lambda cell: (cell[1], cell[0])))

        blocks.sort(key=lambda block: (block[0][1], block[0][0]))
        bands = sorted({block[0][1] for block in blocks})
        columns = sorted({block[0][0] for block in blocks})

        for block in blocks:
            band = bands.index(block[0][1])
            column = columns.index(block[0][0])
            letter = RACK_BANDS[band] if band < len(RACK_BANDS) else f"R{band + 1}"
            island_code = f"{letter}{column + 1}"
            slot_ids = []
            for number, cell in enumerate(block, start=1):
                access = None
                # Prefer the west aisle, then east, then north, then south, so
                # neighbouring islands hand their traffic to different aisles.
                for candidate in (
                    (cell[0] - 1, cell[1]),
                    (cell[0] + 1, cell[1]),
                    (cell[0], cell[1] - 1),
                    (cell[0], cell[1] + 1),
                ):
                    if self._structurally_walkable(*candidate):
                        access = candidate
                        break
                if access is None:
                    continue  # a fully enclosed shelf cell is not addressable
                slot = {
                    "id": len(self.rack_slots),
                    "code": f"{island_code}-{number:02d}",
                    "island": island_code,
                    "cell": cell,
                    "access": access,
                    "state": "empty",   # "empty" | "reserved" | "stored"
                    "task_id": None,
                    "cargo_id": None,
                }
                self.rack_slots.append(slot)
                slot_ids.append(slot["id"])
            self.rack_islands.append({
                "code": island_code,
                "cell": block[0],
                "size": len(block),
                "slots": slot_ids,
            })

    def rack_access_cells(self, slot_cell) -> list[tuple[int, int]]:
        """All structural aisle faces of the SAME shelf cell, not nearby slots.

        Keep barriers out of this definition: the robot planner evaluates their
        live reachability. Never reach diagonally or through another shelf.
        """
        x, y = tuple(slot_cell)
        if not (0 <= x < self.width and 0 <= y < self.height) or self.grid[y][x] != SHELF:
            return []
        return [cell for cell in ((x-1, y), (x+1, y), (x, y-1), (x, y+1))
                if self._structurally_walkable(*cell)]

    def get_slot(self, slot_id: int) -> dict | None:
        if slot_id is None or not (0 <= slot_id < len(self.rack_slots)):
            return None
        return self.rack_slots[slot_id]

    def free_slots(self) -> list[dict]:
        return [slot for slot in self.rack_slots if slot["state"] == "empty"]

    def reserve_slot(self, slot_id: int, task_id: int) -> bool:
        slot = self.get_slot(slot_id)
        if slot is None or slot["state"] != "empty":
            return False
        slot["state"] = "reserved"
        slot["task_id"] = task_id
        return True

    def mark_slot_stored(self, slot_id: int) -> bool:
        slot = self.get_slot(slot_id)
        if slot is None:
            return False
        slot["state"] = "stored"
        return True

    def release_slot(self, slot_id: int) -> bool:
        slot = self.get_slot(slot_id)
        if slot is None:
            return False
        slot["state"] = "empty"
        slot["task_id"] = None
        slot["cargo_id"] = None
        return True

    def reset_racks(self):
        """Empty every slot. Called when a demonstration restarts."""
        for slot in self.rack_slots:
            slot["state"] = "empty"
            slot["task_id"] = None
            slot["cargo_id"] = None

    def stored_slots(self) -> list[dict]:
        return [slot for slot in self.rack_slots if slot["state"] == "stored"]

    # ─── Navigation ────────────────────────────────────────────────────────

    def is_walkable(self, x: int, y: int) -> bool:
        """Return True if cell (x,y) is in bounds, not SHELF/WALL, not blocked."""
        return (
            0 <= x < self.width
            and 0 <= y < self.height
            and self.grid[y][x] not in (SHELF, WALL)
            and (x, y) not in self.blocked_cells
        )

    def get_neighbors(self, x: int, y: int) -> list[tuple[int, int]]:
        """Return walkable 4-connected neighbors."""
        candidates = [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
        return [(nx, ny) for nx, ny in candidates if self.is_walkable(nx, ny)]

    def block_aisle(self, x: int, y: int):
        self.blocked_cells.add((x, y))

    def unblock_aisle(self, x: int, y: int):
        self.blocked_cells.discard((x, y))

    def set_occupancy(self, robot_id: int, cell: tuple[int, int]):
        """Record where a robot physically is."""
        self.robot_occupancy[robot_id] = cell

    def to_serializable(self) -> dict:
        return {
            "id": getattr(self, "warehouse_id", "warehouse_default"),
            "name": getattr(self, "name", "Warehouse"),
            "theme": getattr(self, "theme", "classic_daylight"),
            "width": self.width,
            "height": self.height,
            "grid": self.grid,
            "blocked": list(self.blocked_cells),
            "pickups": self.pickup_points,
            "dropoffs": self.dropoff_points,
            "chargers": self.charging_stations,
            "zones": getattr(self, "zones", []),
            "markings": getattr(self, "markings", []),
            "exterior_assets": getattr(self, "exterior_assets", []),
            "semantic_locations": self.semantic_locations(),
            "consolidation": self.consolidation,
            "tables": [
                {
                    "id": table["id"],
                    "code": table["code"],
                    "cell": list(table["cell"]),
                    "side": table["side"],
                    "state": table["state"],
                    "task_id": table["task_id"],
                }
                for table in self.tables
            ],
            "racks": [
                {
                    "id": slot["id"],
                    "code": slot["code"],
                    "island": slot["island"],
                    "cargo_id": slot.get("cargo_id"),
                    "cell": list(slot["cell"]),
                    "access": list(slot["access"]),
                    "state": slot["state"],
                    "task_id": slot["task_id"],
                }
                for slot in self.rack_slots
            ],
            "rack_islands": [
                {"code": island["code"], "cell": list(island["cell"]), "size": island["size"]}
                for island in self.rack_islands
            ],
        }
