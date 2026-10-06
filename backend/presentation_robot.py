"""Server-only handling dwell; the original Robot/headless benchmark stay unchanged.
Cargo ownership changes only after HANDLING_TICKS, while the occupied cell is
reserved through normal P2P position broadcasts. Pause and speed use server ticks.

The dwell also carries the information the 3D view needs to animate a real
warehouse transfer: whether the carton is moving to/from a table or a rack
slot, which cell it is reaching into, and which way the unit must face.
"""
import time
from robot import Robot
from config import BATTERY_DRAIN_IDLE
HANDLING_TICKS = 10


def _face(from_cell, to_cell) -> int:
    """Backend heading (0=+x, 90=+y, 180=-x, 270=-y) from one cell to another."""
    dx = to_cell[0] - from_cell[0]
    dy = to_cell[1] - from_cell[1]
    if dx > 0:
        return 0
    if dx < 0:
        return 180
    if dy > 0:
        return 90
    if dy < 0:
        return 270
    return 0


class PresentationRobot(Robot):
    def __init__(self, robot_id, start_pos, warehouse, battery=None):
        if battery is None:
            super().__init__(robot_id, start_pos, warehouse)
        else:
            super().__init__(robot_id, start_pos, warehouse, battery)
        self.handling = None
        self._handling_start = None

    def _handle_arrival(self, tick, p2p_network):
        if not self.current_task:
            return super()._handle_arrival(tick, p2p_network)
        if self.handling is None:
            task = self.current_task
            kind = "dropoff" if self.carrying else "pickup"
            station = list(task["dropoff" if self.carrying else "pickup"])
            place = task.get("dropoff_kind" if self.carrying else "pickup_kind", "table")
            slot_cell = task.get(f"{kind}_slot_cell") or task.get("slot_cell")
            if place == "rack" and slot_cell:
                target = list(slot_cell)
            else:
                direction = {
                    "north": (0, -1),
                    "south": (0, 1),
                    "west": (-1, 0),
                    "east": (1, 0),
                }.get(task.get(f"{kind}_side") or task.get("table_side"), (1, 0))
                target = [station[0] + direction[0], station[1] + direction[1]]
            self.handling = {
                "kind": kind,
                "task_id": task["id"],
                "station": station,
                "progress": 0.0,
                "place": place,
                "target": target,
                "face": _face((self.x, self.y), target),
                "stage": task.get("stage", "direct"),
                "slot_code": task.get(f"{kind}_slot_code") or task.get("slot_code"),
            }
            self._handling_start = tick
            self.status = "placing" if self.carrying else "picking_up"
            self.is_yielding = False
            self.consecutive_waits = 0
            self.planned_path = []
            self.path_index = 0
            self._broadcast_position(p2p_network, tick)
            self._broadcast_intent(p2p_network, tick)
        return "handling"

    def tick(self, current_tick, p2p_network, event_logger=None):
        if self.handling is None:
            return super().tick(current_tick, p2p_network, event_logger)
        start = time.perf_counter()
        self.prev_x, self.prev_y = self.x, self.y
        self._process_messages(p2p_network.receive_all(self.id), event_logger, current_tick)
        self.battery = max(0.0, self.battery - BATTERY_DRAIN_IDLE)
        elapsed = current_tick - self._handling_start
        self.handling["progress"] = min(1.0, max(0.0, elapsed / HANDLING_TICKS))
        self._broadcast_position(p2p_network, current_tick)
        self._broadcast_intent(p2p_network, current_tick)
        if elapsed >= HANDLING_TICKS:
            self.handling = None
            self._handling_start = None
            action = super()._handle_arrival(current_tick, p2p_network)
        else:
            action = "handling"
        self.decision_time_ms = (time.perf_counter() - start) * 1000
        return action

    def _broadcast_intent(self, p2p_network, tick):
        if self.handling:
            p2p_network.broadcast(self.id, "intent", {"path": [], "dist": 0, "tick": tick})
        else:
            super()._broadcast_intent(p2p_network, tick)

    def _go_to_charging(self, p2p_network=None, tick=0):
        # Never abandon a transfer half-done: an in-progress lift or placement
        # finishes first, then the unit books a pad on the next tick.
        if self.handling is None:
            super()._go_to_charging(p2p_network, tick)

    def park_for_charging(self, p2p_network=None, tick=0, event_logger=None):
        # Same rule for the end-of-round dock: a carton in mid-air is never
        # left hanging because the round finished.
        if self.handling is not None:
            return False
        return super().park_for_charging(p2p_network, tick, event_logger)

    def to_dict(self):
        result = super().to_dict()
        result["handling"] = dict(self.handling) if self.handling else None
        return result
