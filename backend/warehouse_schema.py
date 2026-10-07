"""Standard Warehouse Definition Schema.

Defines a declarative, versioned, validated specification for multi-agent AMR
warehouse environments using Pydantic v2.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


VALID_CELL_CHARS = {".", "#", "W", "P", "D", "C"}


class WarehouseDimensions(BaseModel):
    """Spatial dimensions and resolution of the warehouse grid."""
    width: int = Field(..., ge=4, le=500, description="Number of grid columns (X-axis).")
    height: int = Field(..., ge=4, le=500, description="Number of grid rows (Y-axis / Z-axis in 3D).")
    cell_size: float = Field(default=1.0, gt=0.0, le=10.0, description="Physical size of one cell in meters.")


class WarehouseMetadata(BaseModel):
    """Metadata describing facility provenance and modeling context."""
    author: str = Field(default="SIH 26123 Team", description="Author or engineering team.")
    created_at: str = Field(default="", description="ISO-8601 date string.")
    facility_type: str = Field(default="distribution_center", description="Warehouse topology classification.")
    unit: str = Field(default="meter", description="Measurement unit for dimensions.")


class StoredCarton(BaseModel):
    slot: str
    cargo_id: str = Field(min_length=1)


class ConsolidationSettings(BaseModel):
    target_rack: str = Field(min_length=1)
    capacity: int = Field(ge=1)
    initial_inventory: list[StoredCarton] = Field(default_factory=list)


class OperationalSettings(BaseModel):
    """Simulation and operational parameters associated with the facility."""
    target_islands: list[int] | None = Field(
        default=None,
        description="Indices of rack islands targeted for sequential putaway. None to spread across all."
    )
    consolidation: ConsolidationSettings | None = None
    default_num_robots: int = Field(default=3, ge=1, le=50, description="Default fleet size for this floor.")
    robot_starts: list[tuple[int, int]] = Field(
        default_factory=list,
        description="Recommended initial spawn coordinates for AMR units."
    )


class StationDefinition(BaseModel):
    """Explicit semantic staging table / pickup / dropoff station."""
    id: int = Field(..., ge=0)
    code: str = Field(..., min_length=1, max_length=16)
    cell: tuple[int, int]
    side: Literal["west", "east", "north", "south", "central"] = "west"
    station_type: Literal["table", "pickup", "dropoff"] = "table"


class ChargerDefinition(BaseModel):
    """Inductive charging pad station."""
    id: int = Field(..., ge=0)
    code: str = Field(..., min_length=1, max_length=16)
    cell: tuple[int, int]


class ZoneDefinition(BaseModel):
    """Semantic operations zone (storage quadrant, sorting, charging island, dock area)."""
    id: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=64)
    category: Literal["storage", "staging", "charging", "restricted", "sortation", "auxiliary"] = "auxiliary"
    bounds: tuple[int, int, int, int] = Field(..., description="(min_x, min_y, max_x, max_y) bounding box")
    color: str = Field(default="#2563eb", description="Hex badge / perimeter color")
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoadwayMarking(BaseModel):
    """Floor navigation marking (zebra crosswalk, lane lines, arrows, hazard borders)."""
    type: Literal["crosswalk", "lane_divider", "arrow", "hazard_border"]
    start: tuple[int, int]
    end: tuple[int, int]
    direction: str = Field(default="")


class ExteriorAsset(BaseModel):
    """Exterior architectural elements (dock doors, parked freight trucks, roller ramps)."""
    type: Literal["dock_door", "freight_truck", "conveyor_ramp"]
    position: tuple[int, int]
    orientation: Literal["north", "south", "east", "west"] = "south"
    color: str = Field(default="#1e3a8a")


class WarehouseDefinition(BaseModel):
    """Complete standard warehouse environment specification."""
    id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$", description="Unique warehouse slug.")
    name: str = Field(..., min_length=1, max_length=128, description="Human-readable facility name.")
    version: str = Field(default="1.0.0", description="Semantic version of this warehouse layout.")
    description: str = Field(default="", description="Detailed summary of topology and aisle layout.")
    dimensions: WarehouseDimensions
    theme: str = Field(default="classic_daylight", description="Rendering theme preset for digital twin")
    layout: list[str] = Field(..., min_length=4, description="ASCII grid matrix defining physical structure.")
    metadata: WarehouseMetadata = Field(default_factory=WarehouseMetadata)
    operational_settings: OperationalSettings = Field(default_factory=OperationalSettings)
    stations: list[StationDefinition] = Field(default_factory=list)
    chargers: list[ChargerDefinition] = Field(default_factory=list)
    zones: list[ZoneDefinition] = Field(default_factory=list)
    markings: list[RoadwayMarking] = Field(default_factory=list)
    exterior_assets: list[ExteriorAsset] = Field(default_factory=list)

    @field_validator("layout")
    @classmethod
    def validate_layout_chars(cls, rows: list[str]) -> list[str]:
        for y, row in enumerate(rows):
            for x, char in enumerate(row):
                if char not in VALID_CELL_CHARS:
                    raise ValueError(
                        f"Invalid cell character '{char}' at position ({x}, {y}). "
                        f"Allowed characters: {sorted(VALID_CELL_CHARS)}"
                    )
        return rows

    @model_validator(mode="after")
    def validate_dimensions_match_layout(self) -> WarehouseDefinition:
        expected_height = self.dimensions.height
        expected_width = self.dimensions.width
        actual_height = len(self.layout)
        if actual_height != expected_height:
            raise ValueError(
                f"Layout row count ({actual_height}) does not match dimensions.height ({expected_height})."
            )
        for y, row in enumerate(self.layout):
            if len(row) != expected_width:
                raise ValueError(
                    f"Layout row {y} width ({len(row)}) does not match dimensions.width ({expected_width})."
                )
        return self

    @classmethod
    def from_file(cls, path: str | Path) -> WarehouseDefinition:
        """Load and validate a warehouse definition from a JSON file."""
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Warehouse definition file not found: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)

    def to_file(self, path: str | Path) -> None:
        """Save this warehouse definition to a formatted JSON file."""
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def export_json_schema(cls) -> dict:
        """Generate JSON Schema representation for ROS2 and external tooling."""
        return cls.model_json_schema()
