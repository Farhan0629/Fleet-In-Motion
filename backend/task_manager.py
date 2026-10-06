import random

from config import robot_name, TARGET_ISLANDS

# Which rack island each staged carton is routed to. The order deliberately
# hops between bands and columns so the twelve putaway runs spread over the
# aisles instead of queueing into one corridor.
ISLAND_ORDER = (0, 4, 8, 2, 6, 1, 5, 7, 3)


class Task:
    """One physical carton and the single leg it has to travel.

    A carton has a stable id and exactly ONE location at any moment: the
    staging table it was received on, the arms of the unit carrying it, or the
    rack slot it was put away in. There is no stage in which it exists twice,
    and none in which it appears from nowhere.

      direct    loading table -> delivery table   (headless benchmark only)
      putaway   staging table -> rack slot        RECEIVE -> PUTAWAY -> STORE

    A putaway task is finished when the carton is on the shelf, and it stays
    there. Stored inventory is never pulled back out to manufacture more work,
    which is exactly the illusion the earlier two-leg cycle created on screen.
    """
    _counter = 0

    def __init__(self, pickup, dropoff, stage="direct", slot=None, table=None, destination=None):
        Task._counter += 1
        self.id = Task._counter
        self.pickup = pickup
        self.dropoff = dropoff
        self.assigned_to = None  # robot_id or None
        self.status = "pending"  # "pending" | "assigned" | "completed"
        self.stage = stage       # "direct" | "putaway"
        self.origin = pickup                      # table the carton arrived on
        self.destination = destination or dropoff  # where it ends up resting
        self.table_id = table["id"] if table else None
        self.table_code = table["code"] if table else None
        self.slot_id = slot["id"] if slot else None
        self.slot_code = slot["code"] if slot else None
        self.slot_cell = tuple(slot["cell"]) if slot else None
        self.slot_access = tuple(slot["access"]) if slot else None
        self.pickup_kind = "table"
        self.dropoff_kind = "rack" if stage == "putaway" else "table"

    def as_payload(self) -> dict:
        """What a robot (and the 3D view) needs to know about this carton."""
        return {
            "id": self.id,
            "pickup": self.pickup,
            "dropoff": self.dropoff,
            "stage": self.stage,
            "pickup_kind": self.pickup_kind,
            "dropoff_kind": self.dropoff_kind,
            "table_code": self.table_code,
            "slot_code": self.slot_code,
            "slot_id": self.slot_id,
            "slot_cell": list(self.slot_cell) if self.slot_cell else None,
            "origin": list(self.origin),
            "destination": list(self.destination),
        }


class TaskManager:
    """
    Decentralized task allocation using a simplified bid auction.
    """

    def __init__(self, warehouse, target_islands: list[int] | None = None):
        self.warehouse = warehouse
        # Allow per-warehouse target islands or explicit override; fallback to config.TARGET_ISLANDS
        if target_islands is not None:
            self.target_islands = target_islands
        elif getattr(warehouse, "target_islands", None) is not None:
            self.target_islands = warehouse.target_islands
        else:
            self.target_islands = TARGET_ISLANDS
        # Package labels restart at #1 for every demonstration run.
        Task._counter = 0
        self.pending_tasks: list[Task] = []
        self.active_tasks: list[Task] = []
        self.completed_tasks: list[Task] = []
        self.all_tasks: list[Task] = []
        self.stored_count = 0

    def _choose_slot(self, index: int, pickup: tuple[int, int]) -> dict | None:
        """Reserve an empty rack slot for the carton staged at `pickup`.

        When target_islands is set and valid, the target islands are tried in order so
        that all slots in the first island fill before the second is touched.
        """
        islands = getattr(self.warehouse, "rack_islands", [])
        slots = getattr(self.warehouse, "rack_slots", [])
        if not islands or not slots:
            return None

        valid_targets = [idx for idx in (self.target_islands or []) if idx < len(islands)] if self.target_islands is not None else None

        if valid_targets:
            # Sequential filling: walk through target islands in order and
            # pick the first one that still has an empty slot.
            for island_idx in valid_targets:
                island = islands[island_idx]
                candidates = [
                    slots[sid] for sid in island["slots"]
                    if slots[sid]["state"] == "empty"
                ]
                if candidates:
                    return min(
                        candidates,
                        key=lambda slot: (
                            abs(slot["access"][0] - pickup[0])
                            + abs(slot["access"][1] - pickup[1]),
                            slot["id"],
                        ),
                    )
            return None  # all target islands full

        # Original spread-across-islands logic
        island_idx = ISLAND_ORDER[index % len(ISLAND_ORDER)] % len(islands) if len(islands) > 0 else 0
        island = islands[island_idx]
        candidates = [slots[slot_id] for slot_id in island["slots"] if slots[slot_id]["state"] == "empty"]
        if not candidates:
            candidates = [slot for slot in slots if slot["state"] == "empty"]
        if not candidates:
            return None
        # Within the island, take the face nearest the staging table so the
        # putaway run approaches from the aisle it is already travelling.
        return min(
            candidates,
            key=lambda slot: (
                abs(slot["access"][0] - pickup[0]) + abs(slot["access"][1] - pickup[1]),
                slot["id"],
            ),
        )

    def generate_manifest(self, pairing: list[int] | None = None, storage: bool = False) -> list[Task]:
        """Stage the round before the clock starts. Nothing spawns later.

        `storage=True` builds the demonstration round: one carton on every one
        of the twelve staging tables, each with a rack slot reserved for it.
        The fleet then moves them one at a time, table -> arms -> shelf.

        Without `storage` the original benchmark manifest is produced: six
        cartons on the west loading tables, paired with delivery tables on the
        east (reversed, so every route crosses the floor). `pairing` supplies
        delivery-table indices so the headless benchmark can vary the manifest
        between episodes while keeping the same rule.
        """
        if storage:
            return self._generate_storage_round()

        pickups = list(self.warehouse.pickup_points)
        dropoffs = list(self.warehouse.dropoff_points)
        targets = list(reversed(dropoffs)) if pairing is None else [dropoffs[index] for index in pairing]
        for pickup, dropoff in zip(pickups, targets):
            task = Task(pickup=pickup, dropoff=dropoff)
            self.pending_tasks.append(task)
            self.all_tasks.append(task)
        return list(self.all_tasks)

    def _generate_storage_round(self) -> list[Task]:
        """One carton per staging table, one reserved slot per carton.

        The floor is fully described before the first tick: twelve loaded
        tables, twelve reserved slots, twelve cartons. Every carton a judge
        sees on screen can be traced back to the table it was received on.
        """
        self.warehouse.reset_tables()
        self.warehouse.reset_racks()
        # Pre-fill every island that is NOT a target so it appears occupied.
        valid_targets = [idx for idx in (self.target_islands or []) if idx < len(self.warehouse.rack_islands)] if self.target_islands is not None else None
        if valid_targets:
            target_set = set(valid_targets)
            for idx, island in enumerate(self.warehouse.rack_islands):
                if idx not in target_set:
                    for sid in island["slots"]:
                        slot = self.warehouse.rack_slots[sid]
                        slot["state"] = "stored"
                        slot["task_id"] = None
        for index, table in enumerate(list(self.warehouse.tables)):
            slot = self._choose_slot(index, table["cell"])
            if slot is None:
                break  # no free slot left: stage fewer cartons, never fake one
            task = Task(
                pickup=table["cell"],
                dropoff=tuple(slot["access"]),
                stage="putaway",
                slot=slot,
                table=table,
                destination=tuple(slot["cell"]),
            )
            self.warehouse.reserve_slot(slot["id"], task.id)
            self.warehouse.load_table(table["cell"], task.id)
            self.pending_tasks.append(task)
            self.all_tasks.append(task)
        return list(self.all_tasks)

    def generate_task(self) -> Task:
        """Generate a single random pickup-deliver task (legacy helper)."""
        pickup = random.choice(self.warehouse.pickup_points)
        dropoff = random.choice(self.warehouse.dropoff_points)
        task = Task(pickup=pickup, dropoff=dropoff)
        self.pending_tasks.append(task)
        self.all_tasks.append(task)
        return task

    def find_task(self, task_id: int) -> Task | None:
        for task in self.all_tasks:
            if task.id == task_id:
                return task
        return None

    def remaining(self) -> int:
        """Cartons still to be moved. Zero means the round is over."""
        return len(self.pending_tasks) + len(self.active_tasks)

    def allocate_tasks(self, robots: list, p2p_network, event_logger=None, tick: int = 0) -> list[dict]:
        """
        Run bid allocation for pending tasks.
        Also synchronizes completed tasks from robot states.
        """
        # 1. Handle abandoned tasks (e.g. robot went to charge before pickup)
        for task in self.active_tasks[:]:
            assigned_robot = next((r for r in robots if r.id == task.assigned_to), None)
            if assigned_robot:
                # Robot-selected access may change; shelf destination and slot
                # reservation do not. Keep task telemetry consistent with its unit.
                payload = assigned_robot.current_task
                if (payload and payload.get("id") == task.id and task.dropoff_kind == "rack"
                        and tuple(payload["dropoff"]) in self.warehouse.rack_access_cells(task.slot_cell)):
                    task.dropoff = tuple(payload["dropoff"])
                    task.slot_access = task.dropoff
                charging = (
                    assigned_robot.status in ("charging", "moving_to_charge")
                    or getattr(assigned_robot, "target_charger", None) is not None
                )
                if getattr(assigned_robot, "abandoned_task", None) and assigned_robot.abandoned_task.get("id") == task.id:
                    assigned_robot.abandoned_task = None
                    task.status = "pending"
                    task.assigned_to = None
                    self.active_tasks.remove(task)
                    self.pending_tasks.insert(0, task)
                    if event_logger:
                        event_logger.add_event(
                            "charging",
                            f"Package #{task.id} released back to the fleet auction while {assigned_robot.name} recharges",
                            robot_id=assigned_robot.id,
                            tick=tick,
                        )
                elif assigned_robot.current_task is None and charging:
                    task.status = "pending"
                    task.assigned_to = None
                    self.active_tasks.remove(task)
                    self.pending_tasks.insert(0, task)

        assignments = []

        # 2. Allocate pending tasks to highest bidding idle robots
        for task in self.pending_tasks[:]:
            payload = task.as_payload()
            bids = {}
            for robot in robots:
                bid = robot.calculate_bid(payload)
                if bid > 0:
                    bids[robot.id] = bid

            if not bids:
                continue

            # Winner = highest bid, tiebreak by lowest robot ID
            winner_id = max(bids, key=lambda rid: (bids[rid], -rid))

            task.assigned_to = winner_id
            task.status = "assigned"
            self.pending_tasks.remove(task)
            self.active_tasks.append(task)

            winner = None
            for robot in robots:
                if robot.id == winner_id:
                    winner = robot
                    robot.assign_task(dict(payload))
                    break

            p2p_network.broadcast(winner_id, "result", {
                "task_id": task.id,
                "assigned_to": winner_id,
                "tick": tick
            })

            if event_logger:
                winner_label = getattr(winner, "name", None) or robot_name(winner_id)
                leg = (
                    f"putaway from table {task.table_code} to rack slot {task.slot_code}"
                    if task.stage == "putaway" else "delivery run"
                )
                event_logger.add_event(
                    "auction",
                    f"Package #{task.id} {leg} awarded to {winner_label} \\u2014 highest bid in the fleet auction",
                    robot_id=winner_id,
                    tick=tick
                )

            assignments.append({"task_id": task.id, "robot_id": winner_id})

        return assignments

    def note_pickup(self, task_id: int) -> bool:
        """The carton has physically left its source.

        Called the moment a unit starts lifting, so the table it came from
        reads as empty for the whole transfer instead of holding a ghost copy
        of a carton that is already in the robot's arms.
        """
        task = self.find_task(task_id)
        if task is None:
            return False
        if task.pickup_kind == "table":
            return self.warehouse.mark_table_empty(task.pickup)
        if task.slot_id is not None:
            return self.warehouse.release_slot(task.slot_id)
        return False

    def complete_leg(self, task_id: int):
        """Finish the leg a unit just completed.

        Returns ("stored", task) when a carton was put away in its rack slot,
        ("delivered", task) when a benchmark-style delivery finished, or
        (None, None) if the task was not active.
        """
        for task in self.active_tasks[:]:
            if task.id != task_id:
                continue
            if task.stage == "putaway" and task.slot_id is not None:
                # The slot now physically holds this carton and keeps it.
                self.warehouse.mark_slot_stored(task.slot_id)
                self.stored_count += 1
                outcome = "stored"
            else:
                outcome = "delivered"
            task.status = "completed"
            self.active_tasks.remove(task)
            self.completed_tasks.append(task)
            return outcome, task
        return None, None

    def mark_completed(self, task_id: int):
        """Mark a task as completed."""
        return self.complete_leg(task_id)[0]

    def _serialize(self, task: Task, with_owner: bool = False) -> dict:
        row = {
            "id": task.id,
            "pickup": task.pickup,
            "dropoff": task.dropoff,
            "stage": task.stage,
            "pickup_kind": task.pickup_kind,
            "dropoff_kind": task.dropoff_kind,
            "table_code": task.table_code,
            "slot_code": task.slot_code,
            "slot_cell": list(task.slot_cell) if task.slot_cell else None,
            "destination": list(task.destination),
        }
        if with_owner:
            row["assigned_to"] = task.assigned_to
        return row

    def to_dict(self) -> dict:
        """Serialize task state for WebSocket."""
        return {
            "pending": [self._serialize(t) for t in self.pending_tasks],
            "active": [self._serialize(t, with_owner=True) for t in self.active_tasks],
            "completed": [self._serialize(t) for t in self.completed_tasks[-20:]],
            "completed_count": len(self.completed_tasks),
            "total_count": len(self.all_tasks),
            "stored_count": self.stored_count,
            "in_racks": len([s for s in getattr(self.warehouse, "rack_slots", []) if s["state"] == "stored"]),
            "tables_loaded": len(self.warehouse.loaded_tables()) if hasattr(self.warehouse, "loaded_tables") else 0,
        }
