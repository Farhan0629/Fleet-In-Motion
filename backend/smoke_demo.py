"""Headless replay of the web demonstration: putaway round + end-of-round charging.

Not part of the benchmark. It exists so the demonstration behaviour can be
verified without a browser, and specifically so the "no magic" rules are
machine-checked:

  * twelve tables start loaded, twelve rack slots start empty,
  * a carton is in exactly ONE place on every tick (table, arms or slot) -
    never zero, never two,
  * every table is emptied exactly once and never refilled,
  * a stored carton stays stored (nothing is pulled back out of a rack),
  * when the round is over every unit books a different pad, docks and parks.
"""
import asyncio

from config import NUM_ROBOTS, DEFAULT_ROBOT_STARTS, MAX_TICKS, DEMO_BATTERY_LEVELS
from warehouse import Warehouse
from presentation_robot import PresentationRobot as Robot
from p2p import P2PNetwork
from task_manager import TaskManager
from collision import detect_collisions, detect_deadlock, resolve_deadlock
from events import EventLogger


def audit_cartons(warehouse, robots, tasks) -> list[str]:
    """Every staged carton must be in exactly one physical place."""
    problems = []
    for task in tasks.all_tasks:
        places = []
        table = warehouse.table_at(task.pickup)
        if table and table["state"] == "loaded" and table["task_id"] == task.id:
            places.append(f"table {table['code']}")
        slot = warehouse.get_slot(task.slot_id) if task.slot_id is not None else None
        if slot and slot["state"] == "stored" and slot["task_id"] == task.id:
            places.append(f"slot {slot['code']}")
        for robot in robots:
            holding = robot.carrying and robot.current_task and robot.current_task["id"] == task.id
            transferring = robot.handling is not None and robot.handling["task_id"] == task.id
            if holding or transferring:
                places.append(f"{robot.name}")
                break
        if len(places) != 1:
            problems.append(f"package #{task.id} in {len(places)} places: {places or ['nowhere']}")
    return problems


async def main() -> int:
    warehouse = Warehouse()
    p2p = P2PNetwork()
    tasks = TaskManager(warehouse)
    total = len(tasks.generate_manifest(storage=True))
    logger = EventLogger(max_events=2000)
    robots = [
        Robot(i + 1, DEFAULT_ROBOT_STARTS[i], warehouse, DEMO_BATTERY_LEVELS[i % len(DEMO_BATTERY_LEVELS)])
        for i in range(NUM_ROBOTS)
    ]
    for robot in robots:
        p2p.register_robot(robot.id)

    print(f"tables loaded : {[t['code'] for t in warehouse.loaded_tables()]}")
    print(f"rack islands  : {[island['code'] for island in warehouse.rack_islands]}")
    print(f"slots reserved: {[(s['code'], s['task_id']) for s in warehouse.rack_slots if s['state'] == 'reserved']}")
    print(f"slots stored  : {len([s for s in warehouse.rack_slots if s['state'] == 'stored'])}")
    print(f"opening SoC   : {[(r.name, r.battery) for r in robots]}")

    collisions = pad_conflicts = stored = 0
    carton_problems: list[str] = []
    emptied: dict[str, int] = {}
    stored_history: set[int] = set()
    refilled: list[str] = []
    unstored: list[str] = []
    stored_tick = None
    final = None

    for tick in range(1, MAX_TICKS + 1):
        tasks.allocate_tasks(robots, p2p, logger, tick)
        for robot in robots:
            action = robot.tick(tick, p2p, logger)
            if action == "handling" and robot.handling and robot.handling["progress"] == 0 and robot.handling["kind"] == "pickup":
                tasks.note_pickup(robot.handling["task_id"])
            elif action == "picked_up" and robot.current_task:
                tasks.note_pickup(robot.current_task["id"])
            elif action == "delivered" and robot.last_delivered_task_id:
                outcome, _ = tasks.complete_leg(robot.last_delivered_task_id)
                if outcome == "stored":
                    stored += 1

        # A table may only ever go loaded -> empty, once.
        for table in warehouse.tables:
            if table["state"] == "empty":
                emptied.setdefault(table["code"], tick)
            elif table["code"] in emptied:
                refilled.append(f"{table['code']} refilled at tick {tick}")
        # A stored carton stays stored.
        for slot in warehouse.rack_slots:
            if slot["state"] == "stored":
                stored_history.add(slot["id"])
            elif slot["id"] in stored_history:
                unstored.append(f"{slot['code']} emptied again at tick {tick}")
        carton_problems.extend(audit_cartons(warehouse, robots, tasks)[:1])

        collisions += len(detect_collisions(robots))
        claims: dict[tuple, int] = {}
        for robot in robots:
            pad = robot.target_charger
            if pad is not None:
                if pad in claims:
                    pad_conflicts += 1
                claims[pad] = robot.id
        cycles = detect_deadlock(robots)
        if cycles:
            resolve_deadlock(robots, cycles, warehouse, p2p, tick)

        if stored >= total and stored_tick is None:
            stored_tick = tick
        if stored >= total:
            for robot in robots:
                robot.park_for_charging(p2p, tick, logger)
            if all(robot.parked for robot in robots):
                final = tick
                break

    print("-" * 68)
    print(f"last carton stored: tick {stored_tick}")
    print(f"fleet parked      : tick {final}")
    print(f"putaway complete  : {stored}/{total}")
    print(f"tables emptied    : {len(emptied)}/{len(warehouse.tables)}")
    print(f"slots holding     : {len([s for s in warehouse.rack_slots if s['state'] == 'stored'])}")
    print(f"charge cycles     : {[(r.name, r.charge_cycles, round(r.battery, 1)) for r in robots]}")
    print(f"parked on pads    : {[(r.name, r.target_charger, r.parked) for r in robots]}")
    print(f"collisions        : {collisions}")
    print(f"pad double-books  : {pad_conflicts}")
    print(f"carton anomalies  : {carton_problems[:5] or 'none'}")
    print(f"tables refilled   : {refilled[:3] or 'none'}")
    print(f"slots un-stored   : {unstored[:3] or 'none'}")
    print("-" * 68)
    for event in logger.events:
        if event["type"] in ("charging", "system"):
            print(f"  [{event['type']:>8}] {event['text']}")

    pads = [r.target_charger for r in robots]
    ok = (
        final is not None
        and stored == total == 12
        and len(emptied) == len(warehouse.tables)
        and len([s for s in warehouse.rack_slots if s["state"] == "stored" and s["task_id"] is not None]) == total
        and not carton_problems
        and not refilled
        and not unstored
        and collisions == 0
        and pad_conflicts == 0
        and all(r.parked for r in robots)
        and len(set(pads)) == len(pads)
        and all(pad is not None for pad in pads)
    )
    print("[PASS] putaway round is physically consistent and the fleet parked to charge" if ok else "[FAIL] see counters above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
