# Phase 6 — Dynamic Task System

## Outcome

Phase 6 extends the existing contract-net task auction with runtime semantic missions. It does not
replace A*, P2P coordination, bidding, conflict handling, or warehouse compilation.

Operators can now insert a task while the simulation is running, choose priority, cancel or
reassign uncollected work, change a pending destination, retry cancelled work within a configured
limit, and take an idle or pre-pickup robot out of service. The same `TaskManager` resolves task
locations from each warehouse definition.

## What already existed

- A static startup manifest and contract-net bid allocation.
- Table-to-rack putaway tasks with physical carton ownership.
- Re-auction when a robot abandoned an uncollected task to charge.
- Semantic zones and stations in the Warehouse #2 and #3 definitions.

## What changed

- The runtime `Warehouse` now preserves declared stations and exposes task-facing semantic
  locations.
- Semantic references resolve to validated aisle cells or real rack slots. Robot tasks receive
  coordinates only after this environment-layer resolution.
- Tasks now carry priority, lifecycle status, retry limits, semantic source/destination labels,
  creation tick, and separate pickup/dropoff rack-slot identities.
- Pending tasks are auctioned by priority, then creation time.
- Added create, cancel, reassign, retry, destination-change, and robot-availability WebSocket
  commands.
- Added task creation and lifecycle controls to the existing dashboard.
- Mission completion uses the live queue instead of a manifest-size snapshot, so tasks inserted
  during a run are included.

## Lifecycle and safety rules

`pending → assigned → completed` is the normal path. An uncollected assigned task can return to
`pending`; pending or uncollected work can be cancelled and retried. A carton already on a robot
cannot be cancelled, reassigned, or stranded by taking that robot out of service. That limitation
is explicit: forced mid-carry robot failure and recovery belong to Phase 7.

Rack inventory remains physical:

- rack pickup selects a stored slot and empties it when lifting starts;
- rack dropoff reserves an empty slot and marks it stored after placement;
- table pickup loads that table and empties it when lifting starts;
- one task cannot claim inventory already claimed by another task.

## WH3 physical-clearance contract

The WH3 semantic zones intentionally include operating and service areas larger than their
machines. Earlier rendering placed some solid objects across otherwise valid A* aisle cells.

Zones can declare a rectangular `metadata.navigation_footprint` or multiple
`metadata.navigation_footprints`. The compiler rejects any declared solid footprint containing a
walkable cell. Auxiliary models derive their center and size from the same data. The sortation
loop uses a multipart U-shaped footprint, while the ASRS uses its central machine footprint.

The ASRS transfer decks are ground-supported and contained inside the blocked core. Dock ramps and
decorative bollards that occupied task/aisle cells were removed. This remains a
schema/compiler/rendering correction; no robot-, task-, or warehouse-ID branch was added.

## Verification

Run:

```bash
cd backend
python -m unittest discover -s . -p "test_*.py"

cd ../frontend
npm ci
npm test
npm run build
```

The regression suite checks the complete dynamic lifecycle, priority ordering, semantic task
creation in all three warehouses, robot unavailability/re-auction, rack source and destination
inventory, and zero robot entries into every declared WH3 solid footprint during deterministic
putaway episodes.

## Scope boundary

This is a simulated dynamic task manager. It does not yet implement forced mid-carry robot
failure recovery, station outage policies, large-fleet scaling, arbitrary warehouse import, ROS2,
or physical robot control. Those remain later phases.