# Phase 6 — Dynamic Rack Consolidation

Phase 6 replaces the generic runtime semantic-task editor with one inventory-driven
mission: move existing cartons from occupied racks into a designated empty rack.
There is no second allocator, random task generation, or warehouse-specific robot logic.

## Run it

1. Select Warehouse #1, #2, or #3 while the demonstration is stopped.
2. Click **Prepare inventory** in **Dynamic rack consolidation**. This explicit
   setup replaces the stopped demo's table manifest with the warehouse-defined
   stored inventory. Every non-target rack is occupied; exactly one target is empty.
3. Click **Fill Empty Rack**. This inspects the live inventory without resetting,
   creating new cartons, or changing barriers.
4. Watch target capacity, source availability, generated/pending/active/completed
   tasks, progress, robot assignments, and collision/deadlock counters.

The existing **Start demonstration** command still resets and runs the original
Phase 1–5 table-to-rack putaway scenario. It is separate from consolidation setup.
Preparing another inventory round never overwrites an active or carried transfer.

## Data contract

Each warehouse's `operational_settings.consolidation` declares:

- `target_rack`: an existing compiled rack-island code, not coordinates;
- `capacity`: number of target slots to fill (1 through the compiled slot count);
- `initial_inventory`: explicit `{slot, cargo_id}` records for existing cartons.

The target's slots, shelf cells and aisle access faces come from the compiled
warehouse layout. Fixture validation rejects invalid slots, target inventory,
duplicate slot/cargo IDs and excessive capacity before mutating the floor.
The default capacities are WH1: 4, WH2: 6, WH3: 8. Changing the designated rack or
capacity in data does not change the mission implementation.

## Selection and execution

`ConsolidationMission` is a producer/observer of the existing `TaskManager` queue:

1. Discover unclaimed, stored cartons outside the target.
2. Discover empty target slots up to configured capacity.
3. Evaluate legal pickup/dropoff faces with the existing A*. Reject blocked
   endpoints and routes not reachable from the fleet. Transient robot traffic
   remains the robot/P2P planner's responsibility.
4. Sort feasible source/destination pairs by A* relocation cost, then source and
   destination slot code. Greedily reserve distinct sources and destinations in
   that order; this is deterministic selection, not a global optimizer.
5. Generate rack-to-rack tasks containing separate source/destination slots,
   rack IDs, stable cargo ID, and lifecycle state.
6. The unchanged `allocate_tasks` auction asks robots for their existing bids;
   highest bid wins, existing robot-ID tie-break and P2P result broadcast apply.
7. Existing robot navigation and handling dwell perform pickup → transport →
   placement at the real rack faces and shelf cells.
8. At lift start, the source becomes empty and the transfer animation owns the
   carton. At lift end the robot carries it. At placement end the reserved target
   becomes stored. Cargo identity never changes to a new task ID.
9. Refresh live claims, replenish cancelled/failed uncollected work with other
   feasible cartons, and finish when stored target occupancy reaches capacity.

## Failures and scope

- Missing/invalid target, nonempty target, already-full target: actionable error
  and visible mission state, no implicit reset.
- Insufficient cartons or unreachable source/destination routes: failed/partial
  state with actual occupied capacity, never fabricated success.
- No available robot: work remains queued with `waiting_for_robots`; return a
  robot through the existing availability command to resume bidding.
- Cancellation before pickup releases claims but keeps the source carton stored.
  Cancelled/failed cargo is excluded from automatic reselection that round.
- Losing a claim before pickup fails the task and releases its other reservation.
  Losing a destination during a carried transfer pauses the mission with ownership
  retained rather than placing into an unavailable slot.
- A picked-up carton cannot be cancelled, reassigned, or taken out of service.
- Episode timeout preserves pending/active work and physical ownership. The
  dashboard's **Resume retained mission** continues without inventory reset.
- Robot-local blocked-route telemetry remains visible for mid-mission barriers.

Forced mid-carry robot failure/recovery is not implemented. No Phase 7 work was
started. `robot.py`, `pathfinding.py`, `p2p.py`, `collision.py`, `baseline.py` and
`config.py` are unchanged. Presentation handling only gained cargo-ID telemetry.

## Verification

```bash
cd backend
pip install -r requirements-dev.txt
python -m unittest discover -s . -p 'test_*.py'
cd ../frontend
npm ci
npm test
npm run build
```

Tests cover configured empty-target discovery, inventory discovery, deterministic
lowest-cost selection, valid unique claims, the original auction, physical rack
pickup/placement faces, occupancy conservation every tick, cancellation/failure,
unavailability/reauction, timeout retention, alternate targets/capacity, all three
warehouses, real WebSocket commands and the original putaway start command.

Full-charge deterministic consolidation runs:

| Warehouse | Relocations | Filled at tick | Robots used | Collisions | Deadlocks |
| --- | ---: | ---: | --- | ---: | ---: |
| #1 | 4 | 59 | 1, 2, 3 | 0 | 0 |
| #2 | 6 | 66 | 1, 2, 3 | 0 | 0 |
| #3 | 8 | 109 | 1, 2, 3 | 0 | 0 |

Real WebSocket runs using unchanged default demo batteries also completed and
parked the fleet at ticks 81, 90 and 150 respectively. The local production UI
was exercised through setup → Fill Empty Rack → 100% completion in all warehouses.
