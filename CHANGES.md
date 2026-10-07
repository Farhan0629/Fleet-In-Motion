# Charging cycle + rack storage & retrieval

Two features, implemented end to end (backend simulation, WebSocket contract, 3D twin, dashboard)
and verified with the repo's own test suites.

---

## 1. Battery + autonomous charging cycle

### What a judge now sees

A unit carrying a carton drops under the threshold, keeps its promise and finishes the leg it is
physically holding, then broadcasts a claim on the nearest free pad over the P2P mesh, hands its
remaining work back to the auction, drives to the pad, docks, charges visibly to 100%, releases the
pad and rejoins the fleet.

### Backend

**`config.py`**

| Constant | Value | Note |
| :-- | :-- | :-- |
| `BATTERY_LOW_THRESHOLD` | `50.0` | was `20.0` (per request: detour below 50%) |
| `BATTERY_CHARGE_PER_TICK` | `2.0` | new: ~25 ticks from 50% to full, long enough to watch |
| `BATTERY_CHARGED_LEVEL` | `100.0` | new: undock threshold |
| `DEMO_BATTERY_LEVELS` | `[58.0, 100.0, 76.0]` | new: opening SoC so a charge run happens early |
| `MESSAGE_TYPES` | `+ charger_claim`, `+ charger_release` | new mesh message types |

**`robot.py`** — new `target_charger`, `known_charger_claims`, `charge_cycles`,
`charge_started_tick` fields and:

* `_select_charger(exclude=())` — nearest free pad by real A\* path cost, not Euclidean guesswork.
* `_claim_charger()` / `_release_charger()` — broadcast `charger_claim` / `charger_release`.
* `_resolve_charger_conflict()` — **occupancy negotiation**. If two units claim the same pad, the
  winner is the lower `(path_cost, robot_id)` tuple; the loser re-runs `_select_charger` with the
  contested pad excluded. Deterministic, so it cannot ping-pong.
* `_begin_charging()` / charge tick — `+BATTERY_CHARGE_PER_TICK` per tick, emits `charged` when full.
* `calculate_bid()` returns `0.0` while charging, so a docked unit is never auctioned new work.
* A unit that is **carrying** cargo defers the charge run until the carton is placed (logged once,
  not once per tick).

**`main.py`** — new WebSocket action `drain_battery { robot_id, level? }` (defaults to
`BATTERY_LOW_THRESHOLD - 3`, clamped to `1..BATTERY_MAX`) so the charge run can be triggered on cue
instead of waiting ~90 s of driving. `metrics.record_charge_cycle()` on every completed run.

### Frontend

* **`components/Robot.jsx`** — new `BatteryPack`: a pack mounted on the **back** of the torso
  (`z = -0.2`) with four LED bars that light and change colour with state of charge, a coiled cable
  lead and a connector, plus a pulsing glow while charging.
* **`components/Robot.jsx`** — new `ChargeCable`: a world-space `CatmullRomCurve3` tube from the pad
  post to the connector on the robot's back, with a droop in the middle and a travelling energy
  pulse sphere that runs post → robot while charging. Rendered as a sibling of the robot root so it
  stays in world space and does not inherit the walk bob.
* **`components/Warehouse.jsx`** — new `ChargerPad`: breathing ring, charge post, and a rising
  energy bolt while occupied. The pad sign shows the occupant's or claimant's name, so the P2P
  negotiation is visible on the floor.
* Battery badge on the robot label (`⚡NN%`), chest strip turns green while docked.
* **`dashboard/Controls.jsx`** — per-unit **Force low battery** buttons in the Disruption drills
  block (disabled while that unit is already on a charge run).
* **`dashboard/RobotStatus.jsx`** — battery bar colour-coded by level, pulses while charging, shows
  `Charging · CHARGE n` / `Booked CHARGE n` and a `Charge runs` counter.

---

## 2. Storage & retrieval (putaway / pick from racks)

The nine 2×2 rack islands are no longer scenery. They are addressable inventory.

```
RECEIVE  →  PUTAWAY  →  STORE      inbound table  →  rack slot
PICK     →  PACK     →  DISPATCH   rack slot      →  delivery table
```

### Backend

**`warehouse.py`** — `_extract_rack_slots()` derives **9 islands / 36 slots** from the existing
layout, no hand-maintained coordinate table. Islands are named `A1`…`C3`, slots `A1-01`…`C3-04`.
Each slot carries `{id, code, island, cell, access, state, task_id}` where `access` is the walkable
aisle cell a robot stands in (preference W → E → N → S). New API: `get_slot`, `free_slots`,
`reserve_slot`, `mark_slot_stored`, `release_slot`, `reset_racks`, `stored_slots`.
`to_serializable()` now publishes `racks` and `rack_islands`.

**`task_manager.py`** — a `Task` now has a `stage` (`putaway` | `retrieval` | `direct`), an `origin`
and `destination`, and `pickup_kind` / `dropoff_kind` (`table` | `rack`). `generate_manifest(storage=True)`
spreads slots across islands via `ISLAND_ORDER` so routes fan out over the whole floor instead of
hugging one aisle. `complete_leg()` returns `('stored' | 'delivered', task)`: finishing a putaway leg
does **not** complete the task, it flips the task to a retrieval leg out of that slot. Slots are
reserved on assignment, so two robots can never be sent to the same slot.

**`presentation_robot.py`** — the 10-tick handling dwell now knows where it is reaching: the
`handling` payload carries `place` (`table` | `rack`), `target`, `face`, `stage` and `slot_code`.

**`metrics.py`** — new `packages_stored` and `charge_cycles` counters, so putaway is measured
separately from dispatch and a stored carton is never double-counted as delivered.

### Frontend

* **`components/Warehouse.jsx`** — rack slots are live. The decorative carton in a slot is skipped
  when the slot is claimed, and a real `CargoBox` is drawn in its place; the access aisle cell tints
  green (stored) or amber (reserved). Each island gets an `A1`…`C3` sign so the slot codes in the
  dashboard match the floor.
* **`utils/presentation.js`** — `transferPose()` is rack-aware, with separate reach heights for the
  low and high shelf views and labels like *Reaching into rack*, *Lifting off shelf*,
  *Sliding onto shelf*.
* **`utils/simulationState.js`** — new `storing` / `retrieving` statuses, `RACK <slot>` as a next
  destination, and `stored` / `inRacks` in the mission summary.
* **`dashboard/TaskQueue.jsx`** — stage chips (`putaway` / `retrieval` / `direct`), slot codes on
  every rack leg, and the two-flow legend.
* **`dashboard/Dashboard.jsx`**, **`MetricsPanel.jsx`**, **`EventLog.jsx`**, **`App.jsx`** — an
  *In racks* chip, *Put away in racks* and *Autonomous charge runs* tiles, a `Storage` event label,
  and the viewport caption is now `RECEIVE → PUTAWAY → STORE · PICK → PACK → DISPATCH`.

---

## Verification (all run, all green)

```
python3 -m py_compile *.py                              COMPILE_OK
python3 -m unittest test_presentation_contract -v        6/6 OK
python3 smoke_demo.py                                    PASS
cd frontend && node --test src/utils/*.test.js          16/16 OK
```

`smoke_demo.py` (new, headless, no server needed) runs a full episode and asserts the things that
are easy to get wrong:

```
islands              : A1 A2 A3 B1 B2 B3 C1 C2 C3   (36 slots)
opening SoC          : Farhan 58.0  Debojyoti 100.0  Gaurav 76.0
ticks                : 209
put away             : 6/6
dispatched           : 6/6
charge cycles        : Farhan 1 (74.2)  Debojyoti 0  Gaurav 1 (79.9)
collisions           : 0
pad double-books     : 0
slots left dirty     : []
```

The 100-episode benchmark (`test_simulation.py`) still reports **81.0 ticks vs 100.2 baseline =
19.2 % faster, 0 collisions, 100/100 completed**, byte-identical to the number already in the
README, and it now also asserts a new invariant: **`double-booked charge pads : 0`**.

> The benchmark's `[FAIL] headline improvement 19.2% is below the 20% target` line is pre-existing
> and unchanged by this work — the headless benchmark constructs plain `robot.Robot` with a full
> battery and no storage manifest, so charging and putaway do not perturb it. It is a measured
> result, not a crash.

---

## README rows to update

Two small edits keep the docs honest:

1. In **Configuration & Tuning**, `BATTERY_LOW_THRESHOLD` is now `50.0`, and add:

```
| `BATTERY_CHARGE_PER_TICK` | `2.0`   | Battery recovered per tick while docked on a pad |
| `BATTERY_CHARGED_LEVEL`   | `100.0` | Level at which a unit undocks and releases the pad |
| `DEMO_BATTERY_LEVELS`     | `[58.0, 100.0, 76.0]` | Opening SoC per unit for the live demo |
| `STORAGE_FLOW_ENABLED`    | `True`  | Route packages through rack slots instead of table-to-table |
```

2. In **Demonstration Walkthrough**, the flow is now two legs
   (`RECEIVE → PUTAWAY → STORE`, then `PICK → PACK → DISPATCH`), and there is a third drill:
   *Force low battery* → watch the unit claim a pad over the mesh, hand its package back, dock and
   resume.

---

## Phase 5 — Warehouse #3

Added the declarative 36×24 Automated Cross-Dock & ASRS Campus, generic north/south dock asset
orientation, a third facility selector, deterministic Warehouse #3 regression metrics, and the
Phase 5 validation report. Existing Warehouse #1/#2 definitions, robot coordination algorithms,
and benchmark baselines remain unchanged.

### Phase 5 visual refinement

Replaced the ASRS placeholder slabs with detailed high-bay racks, visible inventory, stacker-crane
frames, lift carriages, elevated conveyors, and safety fencing. Long in-world labels now
automatically widen and fit their font sizes instead of clipping. Navigation and simulation logic
were not changed.

---

## Phase 6 — Dynamic semantic tasks

Extended the existing contract-net task manager with priority-aware runtime task creation,
cancellation, reassignment, retry, pending destination changes, and pre-pickup robot availability.
Task endpoints are resolved through warehouse stations/zones and use independent pickup/dropoff
rack slots, so the same lifecycle works in Warehouses #1, #2, and #3.

Also corrected the WH3 ASRS render/navigation mismatch with a compiler-validated generic solid
navigation footprint. No robot-specific or warehouse-ID-specific coordination branch was added.
See `PHASE6_DYNAMIC_TASKS.md` for behavior, tests, and limitations.

### Warehouse #3 full physical-clearance audit

Extended the footprint contract to multipart machinery and applied it to every custom solid in
WH3. The navigation grid now blocks the sortation conveyor, ASRS core, workbenches, pallet stacks,
control room, maintenance station, dispatch buffer, and returns station. Rendering uses those same
footprints. Unsupported elevated ASRS conveyors were replaced with grounded transfer decks inside
the machine core; dock ramps and aisle bollards were removed.

The corrected topology remains connected. Three headless episodes and one complete live-server
episode completed all 12 putaway tasks with zero collisions and zero positions or published paths
inside declared solid footprints. The previous Phase 5 baseline remains documented separately.

### Final table approach clearance

Preserved station service-side metadata in the runtime warehouse and moved table fixtures out of
their robot service cells. North/south/east/west tables now orient consistently, and handling
animation faces the real fixture side. This prevents robots from visually walking through tables
without changing A*, task allocation, or warehouse-specific robot behavior.


## Phase 6 rebuild — Dynamic rack consolidation

Replaced generic task insertion, retry and destination-editing controls/API with
explicit warehouse inventory preparation and Fill Empty Rack. Added declarative
target/capacity/carton fixtures to all three warehouses, deterministic feasible
A* relocation selection, stable cargo IDs, claim-safe cancellation/failure and
live mission telemetry. Reused existing queue, bidding, P2P coordination and rack
handling/placement. Core robot intelligence and Phase 1–5 behavior are unchanged.

Consolidation and inventory-conservation tests pass on WH1 (4 slots), WH2 (6) and
WH3 (8), with zero collisions/deadlocks. WebSocket tests also exercise default
batteries, fleet parking and the original putaway start command. Frontend tests
and production build pass. See PHASE6_DYNAMIC_TASKS.md. No Phase 7 work included.


## Phase 7 — Fleet resilience and recovery

Extended the working consolidation queue with original-task failure recovery.
Before pickup, claims are released/revalidated and the existing auction selects
another robot. Carrying failure freezes the real owner/body, retains the original
target reservation and performs an adjacent animated handoff before delivery.
Stable cargo identity and inventory conservation remain intact.

Extended existing P2P partitions with local mode, stale-connection/motion rejection
and bidirectional current position/task/cargo/destination/charger reconciliation.
Added a compact, state-valid resilience drill panel and measured recovery counters.
No second allocator/network or warehouse-specific recovery logic. No ROS2, physical
control, scalability, consensus or Phase 8 work. See PHASE7_RESILIENCE.md for flows,
functional test results and scope boundaries.
