# Phase 5 — Warehouse #3 Validation

## Outcome

Phase 5 adds `warehouse_3.json`, an automated cross-dock and ASRS campus inspired by the supplied
warehouse blueprint. It is a new environment definition, not a new robot implementation.

The same `PresentationRobot`, A* planner, P2P network, contract-net allocation, conflict handling,
deadlock resolution, battery model, and charging workflow used by Warehouses #1 and #2 run in
Warehouse #3 without an ID-specific algorithm branch.

## What already existed

- A validated, declarative warehouse JSON schema.
- `EnvironmentEngine` compilation and topology checks.
- A runtime `Warehouse` abstraction consumed by robot intelligence.
- Data-driven Three.js rendering for racks, stations, zones, markings, docks, and trucks.
- Runtime warehouse switching and fleet reinitialization.
- Deterministic headless simulation tests.

## What changed

- Added a 36×24 Warehouse #3 definition with:
  - opposing inbound and outbound docks;
  - west high-density storage banks;
  - a central ASRS structural core with ring corridors;
  - sortation and induction;
  - a central eight-pad charging court;
  - east-side picking, QA, packing, control, and reverse-logistics areas;
  - maintenance, dispatch buffer, road markings, trucks, and dock doors.
- Extended the existing generic freight-truck/apron rendering to respect asset orientation. WH2's
  south-facing assets retain their previous behavior.
- Added a third facility selector to the existing dashboard.
- Added deterministic Warehouse #3 topology, reuse, slot-targeting, and simulation tests.

## Compiled environment metrics

| Metric | Warehouse #3 |
| --- | ---: |
| Dimensions | 36×24 |
| Total cells | 864 |
| Walkable cells | 637 |
| Shelf cells | 60 |
| Wall cells | 167 |
| Connected components | 1 |
| Aisle graph diameter | 54 cells |
| Staging tables | 12 |
| Rack islands | 8 |
| Rack slots | 60 |
| Charging pads | 8 |
| Semantic zones | 17 |
| Exterior assets | 24 |

## Deterministic simulation baseline

The Phase 5 test runs three recorded episodes using seeds 501, 502, and 503. The current simulator
is deterministic, so each seed produces the same measured result. Seeds are retained in the result
format for later benchmark expansion; this is not a claim that random scenarios are implemented.

| Metric | Seed 501 | Seed 502 | Seed 503 |
| --- | ---: | ---: | ---: |
| Tasks completed | 12/12 | 12/12 | 12/12 |
| Completion tick | 298 | 298 | 298 |
| Same-cell collisions | 0 | 0 | 0 |
| Swap collisions | 0 | 0 | 0 |
| Deadlocks resolved | 0 | 0 | 0 |
| Replans | 15 | 15 | 15 |
| P2P messages | 2447 | 2447 | 2447 |

These numbers are a Warehouse #3 Phase 5 baseline. They do not replace or alter the existing
Warehouse #1 or Warehouse #2 benchmark results.

## How to test

```bash
python3 -m unittest backend.test_warehouse_3 -v
python3 -m unittest discover -s backend -p "test_*.py"

cd frontend
npm ci
npm test
npm run build
```

For a visual run, start the backend and frontend, select **WH #3 · ASRS Campus 36×24**, and start
the demonstration. Confirm that all twelve cartons are put away, the fleet parks at the charging
court, and switching back to WH1 or WH2 reloads the original environment.

## Scope boundary

This phase is simulation-only. It does not add dynamic runtime task insertion, failure recovery,
scalability benchmarking, arbitrary floor-plan import, ROS2 integration, or physical robot control.
Those remain later phases.

## Visual refinement

The ASRS presentation now models a high-bay storage structure rather than solid placeholder towers:
front and rear shelf grids, occupied storage cells, twin yellow stacker-crane portals and
carriages, roof ties, elevated roller conveyors, support legs, and an operator-side safety fence.
This remains presentation geometry only; the compiled navigation map and robot algorithms are
unchanged.

Shared in-world signage now widens for long titles and fits both title and subtitle fonts to the
available texture width. Labels such as **ASRS · AUTOMATED STORAGE**, **OUTBOUND / DISPATCH
DOCKS**, and **RETURNS & REVERSE LOGISTICS** therefore remain complete instead of being clipped.