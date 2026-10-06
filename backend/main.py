"""FastAPI/WebSocket simulation server. Web demos include handling dwell;
headless benchmark continues to import the original robot.Robot directly.

The demonstration floor is a receiving round with a fully staged manifest:
all twelve staging tables (six west, six east) start with exactly one carton on
them and the rack islands start empty. A unit drives to a table, lifts THAT
carton, carries it and slides it into its reserved slot:
    RECEIVE -> PUTAWAY -> STORE      staging table -> reserved rack slot
The carton then stays on the shelf. Nothing is created, duplicated or pulled
back out of a rack mid-episode, so every carton on screen can be traced to the
table it came from - a table is emptied the instant a unit starts lifting and
is never refilled during the round.

When the last carton is stored the round is over and END_OF_ROUND_CHARGE sends
the whole fleet home: each unit books a pad over the mesh (never the same pad
twice), drives to it, plugs in, charges and parks for the shift.

Three disruption drills are exposed over the socket so a judge can trigger the
hard requirements live:
  * block_aisle      - closes an aisle cell. Cells are chosen by hand from the
                       dashboard (click or drag on the floor) while the demo is
                       paused, or picked by the server when no coordinates are
                       sent. The fleet gossips the hazard over the mesh and each
                       unit replans on its own onboard A* once the floor runs.
  * toggle_partition - simulates a Wi-Fi dead zone. The unit stops receiving
                       and sending mesh traffic and must keep itself safe on
                       onboard sensing alone, which is what \"no central server\"
                       actually has to survive.
  * boost_battery    - maxes out one unit's state of charge to 100% so it can
                       continue operating without needing a charge run.

Barrier edits are only accepted while the simulation is paused or has not been
started, so an obstacle can never appear underneath a unit that is mid-step.
"""
import asyncio
import json
import math
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from config import (
    NUM_ROBOTS, TICK_INTERVAL, MAX_TICKS, DEFAULT_ROBOT_STARTS, FACILITY_BEACON_ID,
    BATTERY_MAX, BATTERY_LOW_THRESHOLD, DEMO_BATTERY_LEVELS, STORAGE_FLOW_ENABLED,
    END_OF_ROUND_CHARGE,
)
from warehouse import Warehouse
from presentation_robot import PresentationRobot as Robot
from p2p import P2PNetwork
from task_manager import TaskManager
from collision import detect_collisions, detect_deadlock, resolve_deadlock
from metrics import MetricsTracker
from baseline import BaselineRobot
from events import EventLogger

app = FastAPI(title="Edge-AI AMR Fleet Coordination")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DEFAULT_WAREHOUSE_FILE = os.path.join(os.path.dirname(__file__), "warehouses", "warehouse_1.json")
if os.path.exists(DEFAULT_WAREHOUSE_FILE):
    warehouse = Warehouse.compile_from_file(DEFAULT_WAREHOUSE_FILE)
    if hasattr(warehouse, "environment_report"):
        print(warehouse.environment_report.summary())
else:
    warehouse = Warehouse()

p2p_network = P2PNetwork()
task_manager = TaskManager(warehouse)
task_manager.generate_manifest(storage=STORAGE_FLOW_ENABLED)
metrics = MetricsTracker()
event_logger = EventLogger()
ROBOT_STARTS = getattr(warehouse, "robot_starts", None) or DEFAULT_ROBOT_STARTS
fleet_size = getattr(warehouse, "num_robots", None) or NUM_ROBOTS


def demo_battery(index: int) -> float:
    """Opening charge for unit `index` in the web demonstration."""
    if not DEMO_BATTERY_LEVELS:
        return float(BATTERY_MAX)
    return float(DEMO_BATTERY_LEVELS[index % len(DEMO_BATTERY_LEVELS)])


robots = [
    Robot(i + 1, ROBOT_STARTS[i % len(ROBOT_STARTS)], warehouse, demo_battery(i))
    for i in range(fleet_size)
]
for robot in robots:
    p2p_network.register_robot(robot.id)
sim_state = {"running": False, "paused": False, "tick": 0, "speed": 0.5}
connected_clients = []
baseline_running = False


def load_and_set_warehouse(warehouse_id: str = "warehouse_1") -> Warehouse:
    """Dynamically switch the active warehouse environment and re-initialize the fleet."""
    global warehouse, ROBOT_STARTS, fleet_size, task_manager
    warehouses_dir = os.path.join(os.path.dirname(__file__), "warehouses")
    target_file = os.path.join(warehouses_dir, f"{warehouse_id}.json")
    if os.path.exists(target_file):
        new_warehouse = Warehouse.compile_from_file(target_file)
    else:
        new_warehouse = Warehouse()

    warehouse = new_warehouse
    ROBOT_STARTS = getattr(warehouse, "robot_starts", None) or DEFAULT_ROBOT_STARTS
    fleet_size = getattr(warehouse, "num_robots", None) or NUM_ROBOTS

    p2p_network.clear_log()
    robots.clear()
    for i in range(fleet_size):
        r = Robot(i + 1, ROBOT_STARTS[i % len(ROBOT_STARTS)], warehouse, demo_battery(i))
        robots.append(r)
        p2p_network.register_robot(r.id)
        p2p_network.restore_robot(r.id)

    task_manager = TaskManager(warehouse)
    staged = len(task_manager.generate_manifest(storage=STORAGE_FLOW_ENABLED))
    metrics.__init__()
    event_logger.clear()
    sim_state.update(running=False, paused=False, tick=0, speed=0.5)
    event_logger.add_event(
        "system",
        f"Switched to {warehouse.name} ({warehouse.width}x{warehouse.height}) with {staged} staged cartons across {len(warehouse.tables)} tables.",
        tick=0,
    )
    return warehouse


def find_robot(robot_id):
    for robot in robots:
        if robot.id == robot_id:
            return robot
    raise ValueError(f"No unit with id {robot_id}")


def floor_is_still():
    """True when barriers may be edited: paused, or not started yet."""
    return not sim_state["running"] or sim_state["paused"]


def pick_choke_cell():
    """Choose an aisle cell that actually disrupts someone.

    Preference order: a cell further along a moving unit's own planned route
    (skipping its next step so the block never lands under its feet), then any
    free cell in the central aisles. Returns None if the floor is wide open.
    """
    occupied = {(robot.x, robot.y) for robot in robots}

    def usable(x, y):
        return (
            0 <= x < warehouse.width
            and 0 <= y < warehouse.height
            and warehouse.grid[y][x] == 0
            and (x, y) not in occupied
            and (x, y) not in warehouse.blocked_cells
        )

    for robot in robots:
        for cell in (robot.planned_path or [])[2:]:
            x, y = cell[0], cell[1]
            if usable(x, y):
                return x, y

    mid_x = warehouse.width // 2
    for dx in range(-2, 3):
        x = mid_x + dx
        if 0 <= x < warehouse.width:
            for y in range(1, warehouse.height - 1):
                if usable(x, y):
                    return x, y
    return None


def build_state_message(tick):
    return {"type": "state_update", "tick": tick, "robots": [r.to_dict() for r in robots], "warehouse": warehouse.to_serializable(), "tasks": task_manager.to_dict(), "metrics": metrics.to_dict(), "p2p_messages": p2p_network.get_recent_messages(20), "events": event_logger.get_recent_events(30), "network": {"partitioned": p2p_network.partitioned_ids()}, "sim": {"running": sim_state["running"], "paused": sim_state["paused"], "speed": sim_state["speed"]}}


async def broadcast_state(state):
    message = json.dumps(state)
    for client in connected_clients[:]:
        try:
            await client.send_text(message)
        except Exception:
            if client in connected_clients:
                connected_clients.remove(client)


async def simulation_loop():
    manifest_size = len(task_manager.all_tasks)
    round_reported = {"stored": False}
    while sim_state["running"]:
        if sim_state["paused"]:
            await asyncio.sleep(0.1)
            continue
        sim_state["tick"] += 1
        tick = sim_state["tick"]
        metrics.episode_ticks = tick
        task_manager.allocate_tasks(robots, p2p_network, event_logger, tick)
        for robot in robots:
            action = robot.tick(tick, p2p_network, event_logger)
            if action == "picked_up" and robot.current_task:
                leg = robot.current_task
                # Belt and braces: the source was already emptied when the lift
                # started, and this call is a no-op if so.
                task_manager.note_pickup(leg["id"])
                source = (
                    f"rack slot {leg.get('slot_code')}" if leg.get("pickup_kind") == "rack"
                    else f"table {leg.get('table_code') or ''} ({robot.x},{robot.y})".replace("  ", " ")
                )
                event_logger.add_event("pickup", f"{robot.name} secured package #{leg['id']} from {source}", robot_id=robot.id, tick=tick)
            elif action == "delivered":
                if robot.last_delivered_task_id:
                    outcome, task = task_manager.complete_leg(robot.last_delivered_task_id)
                    if outcome == "stored":
                        metrics.record_storage()
                        metrics.record_task_completion(tick)
                        event_logger.add_event("storage", f"{robot.name} put package #{task.id} away in rack slot {task.slot_code} \\u2014 the slot holds it from here", robot_id=robot.id, tick=tick)
                    elif outcome == "delivered":
                        metrics.record_task_completion(tick)
                        event_logger.add_event("delivery", f"{robot.name} placed package #{robot.last_delivered_task_id} on delivery table ({robot.x},{robot.y})", robot_id=robot.id, tick=tick)
            elif action == "charged":
                metrics.record_charge_cycle()
            elif action == "handling" and robot.handling and robot.handling["progress"] == 0:
                rack = robot.handling.get("place") == "rack"
                picking = robot.handling["kind"] == "pickup"
                if picking:
                    # The carton leaves its source the moment the lift starts,
                    # so the table (or slot) it came from reads as empty for the
                    # whole transfer instead of showing a duplicate carton.
                    task_manager.note_pickup(robot.handling["task_id"])
                verb = ("lifting out of" if picking else "sliding into") if rack else ("lifting off" if picking else "lowering onto")
                where = f" {robot.handling.get('slot_code')}" if rack else " the table"
                event_logger.add_event("storage" if rack else ("pickup" if picking else "delivery"), f"{robot.name} {verb} package #{robot.handling['task_id']}{where}", robot_id=robot.id, tick=tick)
            elif action == "stepped_aside":
                event_logger.add_event("yield", f"{robot.name} stepped aside to clear a bottleneck", robot_id=robot.id, tick=tick)
            elif action == "waited" and robot.consecutive_waits == 1:
                event_logger.add_event("yield", f"{robot.name} yielding at ({robot.x},{robot.y})", robot_id=robot.id, tick=tick)
        for _ in detect_collisions(robots):
            metrics.record_collision()
        deadlocks = detect_deadlock(robots)
        if deadlocks:
            resolve_deadlock(robots, deadlocks, warehouse, p2p_network, tick)
        # The round is finished when every staged carton is on a shelf. The
        # fleet then takes itself home: book a pad, dock, charge, park.
        round_done = bool(manifest_size) and len(task_manager.completed_tasks) >= manifest_size
        if round_done and END_OF_ROUND_CHARGE:
            if not round_reported["stored"]:
                round_reported["stored"] = True
                event_logger.add_event("system", f"All {manifest_size} packages are on the shelves after {tick} ticks \\u2014 fleet heading to the charging pads", tick=tick)
            for robot in robots:
                robot.park_for_charging(p2p_network, tick, event_logger)
        fleet_parked = all(getattr(robot, "parked", False) for robot in robots) if END_OF_ROUND_CHARGE else True
        if (round_done and fleet_parked) or tick >= MAX_TICKS:
            sim_state["running"] = False
            if round_done:
                stored = metrics.packages_stored
                charges = metrics.charge_cycles
                extra = f" ({charges} charge run(s) during the round)" if charges else ""
                docked = ", ".join(f"{r.name} {r.battery:.0f}%" for r in robots)
                event_logger.add_event("system", f"Round complete in {tick} ticks: {stored} packages put away, fleet parked on the pads{extra} \\u2014 {docked}", tick=tick)
        await broadcast_state(build_state_message(tick))
        if sim_state["running"]:
            await asyncio.sleep(TICK_INTERVAL / max(0.1, sim_state["speed"]))


async def run_baseline_comparison():
    global baseline_running
    try:
        baseline_warehouse = Warehouse(warehouse.raw_layout)
        baseline_robots = [BaselineRobot(i + 1, ROBOT_STARTS[i % len(ROBOT_STARTS)], baseline_warehouse) for i in range(fleet_size)]
        # Same fixed manifest as the live demo so both runs move identical packages.
        pairs = zip(baseline_warehouse.pickup_points, reversed(baseline_warehouse.dropoff_points))
        tasks = [{"id": i + 1, "pickup": pickup, "dropoff": dropoff} for i, (pickup, dropoff) in enumerate(pairs)]
        total = len(tasks)
        task_idx = 0
        for robot in baseline_robots:
            if task_idx < total:
                robot.assign_task(tasks[task_idx]); task_idx += 1
        completed, final_tick = 0, MAX_TICKS
        for tick in range(MAX_TICKS):
            if tick % 20 == 0:
                await asyncio.sleep(0)
            for robot in baseline_robots:
                if robot.tick(baseline_robots) == "delivered":
                    completed += 1
                    metrics.record_baseline_completion(tick)
                    if task_idx < total:
                        robot.assign_task(tasks[task_idx]); task_idx += 1
            if completed >= total:
                final_tick = tick
                break
        metrics.record_baseline_episode(final_tick)
        event_logger.add_event("system", f"Baseline {'completed' if completed >= total else 'timed out'}: {completed}/{total} deliveries. Web demo includes handling dwell, storage legs and charge runs; not a like-for-like benchmark.", tick=sim_state["tick"])
        await broadcast_state(build_state_message(sim_state["tick"]))
    finally:
        baseline_running = False


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    global baseline_running
    await ws.accept()
    connected_clients.append(ws)
    try:
        state = build_state_message(sim_state["tick"])
        state["type"] = "init"
        await ws.send_text(json.dumps(state))
        while True:
            raw = await ws.receive_text()
            try:
                command = json.loads(raw)
                if not isinstance(command, dict):
                    raise ValueError("Command must be an object")
                action = command.get("action")
                if action == "start":
                    if not sim_state["running"] and not baseline_running:
                        sim_state.update(running=True, paused=False, tick=0, speed=0.5)
                        warehouse.blocked_cells.clear()
                        warehouse.reset_racks()
                        p2p_network.clear_log()
                        for i, robot in enumerate(robots):
                            robot.__init__(robot.id, ROBOT_STARTS[i % len(ROBOT_STARTS)], warehouse, demo_battery(i))
                            p2p_network.register_robot(robot.id)
                            p2p_network.restore_robot(robot.id)
                        task_manager.__init__(warehouse)
                        staged = len(task_manager.generate_manifest(storage=STORAGE_FLOW_ENABLED))
                        metrics.__init__()
                        event_logger.clear()
                        if STORAGE_FLOW_ENABLED:
                            summary = (
                                f"{staged} packages staged \\u2014 one carton on every table, racks empty. "
                                f"{', '.join(r.name for r in robots)} will move them one at a time into their reserved "
                                "rack slots (RECEIVE \\u2192 PUTAWAY \\u2192 STORE), then dock on the charging pads "
                                "once the last carton is on a shelf."
                            )
                        else:
                            summary = (
                                f"{staged} packages staged on the loading tables. "
                                f"{', '.join(r.name for r in robots)} will carry each one across to an empty delivery table."
                            )
                        event_logger.add_event("system", summary, tick=0)
                        low = [r.name for r in robots if r.battery <= BATTERY_LOW_THRESHOLD + 10]
                        if low:
                            event_logger.add_event("charging", f"Opening state of charge: {', '.join(f'{r.name} {r.battery:.0f}%' for r in robots)}. Units book a pad over the mesh once they drop below {BATTERY_LOW_THRESHOLD:.0f}%.", tick=0)
                        asyncio.create_task(simulation_loop())
                elif action == "pause" and sim_state["running"]:
                    sim_state["paused"] = not sim_state["paused"]
                    event_logger.add_event("system", "Simulation paused" if sim_state["paused"] else "Simulation resumed", tick=sim_state["tick"])
                    await broadcast_state(build_state_message(sim_state["tick"]))
                elif action == "speed":
                    speed = float(command.get("value", 0.5))
                    if not math.isfinite(speed) or not 0.1 <= speed <= 4:
                        raise ValueError("Speed must be between 0.1 and 4")
                    sim_state["speed"] = speed
                    await broadcast_state(build_state_message(sim_state["tick"]))
                elif action in ("block_aisle", "unblock_aisle"):
                    # Barriers are laid out by hand: the dashboard sends one
                    # command per cell as the operator clicks or drags across
                    # the floor. Editing is only legal while the floor is still,
                    # which the client also enforces - this is the server-side
                    # guarantee that nothing appears under a moving unit.
                    if not floor_is_still():
                        raise ValueError("Pause the demonstration before editing barriers")
                    # Coordinates stay optional: with none, the server picks a
                    # cell on a unit's own route so the drill is guaranteed to
                    # force a live reroute on resume.
                    if command.get("x") is None and action == "block_aisle":
                        cell = pick_choke_cell()
                        if cell is None:
                            raise ValueError("No free aisle cell available to block")
                        x, y = cell
                    else:
                        x, y = int(command["x"]), int(command["y"])
                    if not (0 <= x < warehouse.width and 0 <= y < warehouse.height):
                        raise ValueError("Cell outside warehouse")
                    if action == "block_aisle":
                        if warehouse.grid[y][x] != 0 or any((r.x, r.y) == (x, y) for r in robots):
                            raise ValueError("Block an empty, unoccupied aisle cell")
                        warehouse.block_aisle(x, y)
                        # Gossip the hazard from the facility beacon so every
                        # unit hears it. Broadcasting as robot 1 skipped robot 1.
                        p2p_network.broadcast(FACILITY_BEACON_ID, "blocked", {"x": x, "y": y, "tick": sim_state["tick"]})
                    else:
                        warehouse.unblock_aisle(x, y)
                    event_logger.add_event("hazard", f"Aisle ({x},{y}) {'blocked - hazard gossiped over the mesh, units replanning' if action == 'block_aisle' else 'restored'}", tick=sim_state["tick"])
                    await broadcast_state(build_state_message(sim_state["tick"]))
                elif action == "clear_blocks":
                    cleared = len(warehouse.blocked_cells)
                    warehouse.blocked_cells.clear()
                    event_logger.add_event("hazard", f"{cleared} blocked aisle cell(s) cleared" if cleared else "No blocked aisles to clear", tick=sim_state["tick"])
                    await broadcast_state(build_state_message(sim_state["tick"]))
                elif action == "toggle_partition":
                    robot = find_robot(int(command["robot_id"]))
                    if p2p_network.is_partitioned.get(robot.id, False):
                        p2p_network.restore_robot(robot.id)
                        event_logger.add_event("system", f"{robot.name} reconnected to the mesh", robot_id=robot.id, tick=sim_state["tick"])
                    else:
                        p2p_network.partition_robot(robot.id)
                        event_logger.add_event("hazard", f"{robot.name} lost radio in a Wi-Fi dead zone - navigating on onboard sensors only", robot_id=robot.id, tick=sim_state["tick"])
                    await broadcast_state(build_state_message(sim_state["tick"]))
                elif action == "boost_battery":
                    # Energy boost: max out a unit's battery to full charge.
                    robot = find_robot(int(command["robot_id"]))
                    robot.battery = float(BATTERY_MAX)
                    event_logger.add_event("charging", f"Boost: {robot.name} state of charge set to {robot.battery:.0f}%", robot_id=robot.id, tick=sim_state["tick"])
                    await broadcast_state(build_state_message(sim_state["tick"]))
                elif action == "switch_warehouse":
                    wid = command.get("warehouse_id", "warehouse_1")
                    load_and_set_warehouse(wid)
                    state = build_state_message(0)
                    state["type"] = "init"
                    await broadcast_state(state)
                elif action == "run_baseline" and not baseline_running:
                    baseline_running = True
                    asyncio.create_task(run_baseline_comparison())
            except (ValueError, TypeError, KeyError) as error:
                await ws.send_text(json.dumps({"type": "command_error", "message": str(error)}))
    except WebSocketDisconnect:
        pass
    finally:
        if ws in connected_clients:
            connected_clients.remove(ws)

FRONTEND_DIST = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
if os.path.exists(FRONTEND_DIST):
    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    def serve_frontend():
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
else:
    @app.get("/")
    def root():
        return {"status": "Edge-AI AMR Fleet Coordination Server", "version": "1.6-putaway-round"}

@app.get("/api/status")
def status():
    return {"status": "Edge-AI AMR Fleet Coordination Server", "version": "1.6-putaway-round"}

@app.get("/api/warehouse")
def get_warehouse():
    return warehouse.to_serializable()

@app.get("/api/warehouses")
def list_warehouses():
    warehouses_dir = os.path.join(os.path.dirname(__file__), "warehouses")
    results = []
    if os.path.exists(warehouses_dir):
        for fname in sorted(os.listdir(warehouses_dir)):
            if fname.endswith(".json") and fname != "warehouse_schema.json":
                fpath = os.path.join(warehouses_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    results.append({
                        "id": data.get("id", fname[:-5]),
                        "name": data.get("name", fname),
                        "dimensions": data.get("dimensions", {}),
                        "description": data.get("description", ""),
                        "active": getattr(warehouse, "warehouse_id", "") == data.get("id"),
                    })
                except Exception:
                    continue
    return results

@app.post("/api/warehouses/{warehouse_id}/select")
async def select_warehouse_endpoint(warehouse_id: str):
    load_and_set_warehouse(warehouse_id)
    state = build_state_message(0)
    state["type"] = "init"
    await broadcast_state(state)
    return {"status": "success", "warehouse": warehouse.to_serializable()}

@app.get("/api/metrics")
def get_metrics():
    return metrics.to_dict()
