# Barrier navigation upgrade

## Behavior

- Robots replan from their current cell when barriers are added or removed, even if their radio is partitioned. The whole remaining route is checked, not only the next cell.
- A* searches the entire walkable floor: detours may initially move away from the destination, including backing out of U-shaped barriers.
- Onboard sensing participates in planning as well as collision checks. Sensor-confirmed free cells override stale radio positions. Position and intent memories expire after three broadcast intervals (at least three ticks).
- After three traffic-conflict ticks, robots seek a different route around peer intentions. A safe alternative can be taken immediately, without another unnecessary wait. Every next step still passes collision checks.
- If barriers make every legal destination access unreachable, robot telemetry includes `navigation_message: "Please remove the barrier"` and `navigation_blocked_reason: "barrier"`. The robot card displays that exact text as an accessible alert, and the event log records warning/recovery transitions.
- Removing a barrier that restores connectivity clears the alert and resumes the current task or charging trip on the next simulation tick. Carried cargo is retained.
- Idle robots also warn when barriers close all adjacent exits. Idle/parked robots do not wander just because a barrier is present.

“No route” includes a larger enclosure with free cells inside it, or an enclosed destination; four immediately blocked neighbors are not the only impossible case. A separate diagnostic search ignores barriers solely to distinguish a barrier-caused blockage from an invalid building destination. Diagnostic routes are never used for movement.

Rack deliveries now try every orthogonally adjacent structural aisle face of the SAME reserved shelf cell. Blocking the original face alone does not justify a barrier warning when another face is reachable. Transfer facing and selected-access telemetry follow the chosen face; shelf identity and carton ownership remain unchanged. A sticky fleet alert above the controls makes genuine blockages visible without scrolling to individual robot cards.

Temporary robot traffic is not reported as a barrier enclosure. This change does not promise completion for every arbitrary multi-robot deadlock, exhausted battery, simulation timeout, or physically disconnected layout. Existing deadlock resolution, energy rules, pause controls, and safety checks remain active.

## Try it

1. Start the backend/frontend as described in README.
2. Start the demonstration, pause, and place barriers across an active route.
3. Resume: a unit takes an alternate walkable route if one exists.
4. Pause and enclose a unit (or disconnect all routes to its destination).
5. Resume: its card shows **Please remove the barrier**.
6. Pause and remove a barrier to open a route, then resume: the alert clears and the unit continues.
7. Repeat with its radio offline: local barrier replanning and physical collision checks remain available.

Warnings/recovery update when simulation ticks resume; there is no robot movement while paused.

## Verification

```bash
cd backend
python -m unittest test_barrier_navigation test_rack_access_navigation -v
python -m unittest discover -p 'test_presentation_contract.py' -v
python test_simulation.py
python smoke_demo.py

cd ../frontend
npm ci
npm test
npm run build
```

Results on this branch:

- 30 navigation regression tests passed (18 general barrier tests + 12 rack-access tests). Coverage includes front barriers, U-shaped detours, immediate and larger enclosures, enclosed goals, barrier removal, cargo preservation, charging recovery, offline sensing, expired peer memory, traffic conflicts, 50 seeded barrier maps checked against independent BFS, and a complete 12-package storage mission with three live barriers plus a radio partition.
- 7 existing cargo-handling contract tests passed.
- 29 frontend tests passed, including a rendered dashboard-warning regression; production build passed (existing large-bundle warning remains).
- Existing 100-episode fleet benchmark: 100/100 completed, zero same-cell collisions, zero swap collisions, zero double-booked charge pads. Average fleet time 80.8 ticks vs original 81.0 ticks. The script still exits nonzero because its headline improvement is 19.4%, below its 20% assertion; original code also fails that assertion at 19.2%. No assertions were weakened.
- Existing demo smoke test: 12/12 packages stored, all three robots parked, zero collisions, zero pad conflicts, no cargo anomalies. It still exits nonzero because it counts 36 stored rack-slot records while asserting exactly 12; the same mismatch exists on the original commit. That unrelated inventory-count issue was not changed here.

Base inspected: `572d79851823642bd1a207874a4a36e4574e9e99`.

## Screenshot follow-up: fixed rack access is not the rack itself

The shown packages target C3-02 (shelf cell `(14,15)`, original access `(15,15)`) and C3-04 (shelf cell `(14,16)`, original access `(15,16)`). The former also has a north face `(14,14)`; the latter has a south face `(14,17)`. The initial fix only searched for a path to each original access cell, so it reported a barrier even when the same shelf cell was reachable from its other face.

The regression fixture starts Farhan at `(16,11)` with PKG-010 and Gaurav at `(16,8)` with PKG-009, with the other ten cartons already stored. It explicitly places 26 barriers: column 15 at rows 1..16 and column 4 at rows 1..10. With a southern gap open, both remaining cartons finish at the same reserved slots; carton conservation and collision invariants are checked every tick, including a radio partition. This fixture is inspired by the screenshots, not an exact reconstruction: the screenshots do not reveal every blocked coordinate.

A separate full-wall test blocks column 15 at rows 1..18. No route to either face exists from the east side, so the removal warning is correct even with room for the robot to move. Opening a gap at `(15,18)` restores the route. Robots never cross a barrier, shelf, or wall to fake completion.
