# ─── Default Warehouse Grid (Default Layout) ───
# Note: In the decoupled architecture, Warehouse instances derive their width
# and height dynamically from their layout definition.
GRID_WIDTH = 20          # default columns
GRID_HEIGHT = 20         # default rows
CELL_SIZE = 1.0          # 1 unit = 1 meter in 3D

# ─── Cell Types ───
EMPTY = 0
SHELF = 1
WALL = 2
PICKUP = 3
DROPOFF = 4
CHARGING = 5

# ─── Robot Settings ───
NUM_ROBOTS = 3
ROBOT_SPEED = 1          # cells per tick
BATTERY_MAX = 100
BATTERY_DRAIN_PER_MOVE = 0.5
BATTERY_DRAIN_IDLE = 0.1
# Energy management is autonomous: a unit that drops below this level books a
# pad over the mesh, abandons whatever it has not picked up yet, drives to the
# pad and returns to the auction once it is full again.
BATTERY_LOW_THRESHOLD = 50.0
BATTERY_CHARGE_PER_TICK = 5.0    # inductive pad recovery rate
BATTERY_CHARGED_LEVEL = 100.0    # unplug and rejoin the fleet at this level
SENSOR_RANGE = 5         # cells visible around robot (onboard LiDAR-style sensing)
DEFAULT_ROBOT_STARTS = [
    (1, 1), (1, 10), (1, 18),
    (4, 1), (7, 1), (10, 1),
    (13, 1), (16, 1), (4, 18), (7, 18)
]

# Opening state of charge for the web demonstration only. The headless
# benchmark always starts every unit full, so the coordination numbers are not
# influenced by an artificial energy handicap.
DEMO_BATTERY_LEVELS = [100.0, 100.0, 100.0]

# ─── Fleet Identity ───
# Named units keep the demonstration readable: the 3D labels, the fleet cards
# and the event log all refer to the same three operators.
ROBOT_NAMES = ["Farhan", "Debojyoti", "Gaurav"]


def robot_name(robot_id: int) -> str:
    """Human-readable name for a 1-based robot id. Falls back to UNIT-nn."""
    if 1 <= robot_id <= len(ROBOT_NAMES):
        return ROBOT_NAMES[robot_id - 1]
    return f"UNIT-{robot_id:02d}"


# ─── Simulation ───
TICK_RATE = 10           # ticks per second (10Hz)
TICK_INTERVAL = 1.0 / TICK_RATE  # 0.1 seconds
MAX_TICKS = 2000         # max ticks per episode before timeout

# ─── Collision Avoidance ───
LOOKAHEAD_WINDOW = 5     # check next 5 steps for conflicts
SAFETY_DISTANCE = 1      # minimum cells between robots

# ─── Task Settings ───
# The headless benchmark uses a fixed six-package manifest: one carton per west
# loading table, paired with a delivery table on the east. Nothing spawns
# mid-episode, so every package has a visible origin.
TASKS_PER_EPISODE = 6
TASK_SPAWN_INTERVAL = 10  # legacy knob, unused by the fixed-manifest benchmark

# ─── Storage round (web demonstration) ───
# The demonstration floor is a receiving round, and it is deliberately literal:
#   * every one of the twelve staging tables starts with exactly one carton,
#   * a unit drives to a table, lifts THAT carton, carries it, and slides it
#     into its reserved rack slot:  RECEIVE -> PUTAWAY -> STORE,
#   * the carton stays on the shelf - stored inventory is not teleported back
#     out of the rack to invent more work.
# A carton therefore has exactly one location at every moment (table, arms or
# slot). Nothing is created, duplicated or removed mid-episode.
STORAGE_FLOW_ENABLED = True
STAGED_TABLES = 12               # 6 west + 6 east, one carton each
# When the last carton is on the shelf the round is over: every unit books a
# pad over the mesh, drives to it, plugs in and parks for the shift.
END_OF_ROUND_CHARGE = True

# ─── Sequential rack filling ───
# Indices of rack islands to keep empty (0-based). Robots fill them in this
# order: all slots in the first island, then the second, then the third.
# Every other island starts the round pre-filled ("stored"), so only the
# target islands receive cartons. Set to None to use the original
# spread-across-all-islands behaviour.
TARGET_ISLANDS = [0, 4, 8]       # A1, B2, C3 (diagonal spread)

# ─── P2P Communication ───
P2P_BROADCAST_INTERVAL = 1  # ticks between position broadcasts (10Hz)
FACILITY_BEACON_ID = 0      # pseudo-sender so every robot receives hazard alerts
MESSAGE_TYPES = {
    "POSITION_UPDATE": "pos",
    "INTENT_BROADCAST": "intent",
    "TASK_BID": "bid",
    "TASK_RESULT": "result",
    "BLOCKED_AISLE": "blocked",
    "HEARTBEAT": "heartbeat",
    # Charging pads are a shared, single-occupancy resource. Units negotiate
    # them over the same mesh they use for intents: claim, then release.
    "CHARGER_CLAIM": "charger_claim",
    "CHARGER_RELEASE": "charger_release",
}
