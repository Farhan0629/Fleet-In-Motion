# Phase 7 — Fleet resilience and recovery

Phase 7 extends active Dynamic Rack Consolidation with two drills: robot failure
and P2P communication loss/reconnect. The Phase 1–6 warehouse definitions,
consolidation selection policy, rack placement, navigation, conflict/deadlock
algorithms, battery rules and bid formula remain in place. No second allocator,
network, warehouse-specific recovery branch, or Phase 8 benchmark was added.

## Dashboard workflow

1. Select WH1, WH2 or WH3; **Prepare inventory**, then **Fill Empty Rack**.
2. In **Fleet resilience**, select a robot. Pause if you want a precise drill
   point; 0.25x playback makes before-pickup/after-lift opportunities easy to see.
3. Use **Simulate Robot Failure** before pickup or during carrying. Failure during
   an in-progress lift/placement/handoff is rejected; let the transfer finish.
4. Watch the original task enter recovery, another robot win its auction, and
   the same carton reach the original reserved target slot.
5. **Restore Robot** becomes valid only after the failed unit has no cargo/task.
   Restoration makes it available at its actual location, never teleports it.
6. **Simulate Communication Loss** sets local sensing mode; **Restore
   Communication** exchanges fresh state before normal P2P coordination resumes.

The small section shows failed/offline status, cargo/task recovery, recovery robot,
original destination, failures, successful recoveries, communication losses,
reconciliations, reassigned tasks, recovered cargo, recovery time, collisions,
deadlocks and mission completion. Controls are conditional on current state;
the server independently validates every command.

## Before-pickup failure

- Freeze the robot, mark it failed/unavailable, retain its physical footprint.
- Detach the original task, release source claim and destination reservation.
- The source carton remains stored, with its original stable cargo ID.
- Mark that same task `recovery_pending`, give it urgent existing priority.
- Revalidate and reacquire its original claims before the existing auction.
- The failed robot is excluded; the existing bid formula and robot-ID tie-break
  choose another connected, available robot. Normal rack pickup/delivery follow.
- If original inventory or destination is unavailable, retain the pending task
  with a meaningful recovery-blocked reason rather than inventing inventory.

## Carrying failure and physical handoff

- The failed robot stops where it actually is, still holding the carton. The
  source remains empty and original destination stays reserved to the same task.
- That task enters `recovery_pending`; `cargo_state = recovery_required` and
  `cargo_owner = robot:<failed-id>`. Its stable ID, cargo ID, source history and
  destination identities do not change.
- A recovery-aware payload substitutes only the pickup: walkable cells adjacent
  to the failed unit. Existing A* checks handoff and destination feasibility while
  excluding the failed body's cell. The existing auction still chooses the robot.
- Until the winner reaches physical contact, the failed robot remains sole owner.
- At the start of the adjacent handoff dwell, one atomic custody transition clears
  cargo/task from the failed unit and makes the receiver's transfer the owner.
- The digital twin animates from the failed robot's actual carry pose to the
  receiver's arms. No overlapping robots, duplicate carton or remote teleport.
- At dwell completion, `cargo_recovered` increments, task status becomes
  `recovered`, and normal navigation/placement deliver to the original target.
- On delivery, the slot owns the carton, the task completes, and recovery metrics
  record success/time. Failed bodies remain stopped; mission completion does not
  wait for an immobile failed robot to park on a charger.

Task states for carrying recovery are:

`assigned → recovery_pending → recovery_assigned → recovering → recovered → completed`

Cargo states include `stored`, `pickup_transfer`, `carrying`, `recovery_required`,
`handoff`, and destination `stored`. Ownership is one rack or one robot/robot's
physical transfer at each stage. Recovery reuses the original task queue and ID,
not a second synthetic delivery task.

## Communication loss and reconciliation

The existing `P2PNetwork` partition mechanism is extended, not replaced:

- Block send/receive on the disconnected robot; discard its queued old traffic.
- Increment a per-connection epoch. Packets from an old connection cannot be
  replayed after reconnection, even if they claim a newer simulation tick.
- Invalidate learned position/intent/custody predictions for the offline robot;
  its own peer knowledge is cleared. Existing TTL expiry remains in effect.
- Keep the existing local proximity/occupancy sensing and A* safety checks.
  Assigned work can continue when locally safe; offline robots cannot bid for
  new work. Radio silence never removes a real robot from physical occupancy.
- Restore connectivity only after validating that physical cargo ownership does
  not conflict with task/source inventory.
- Exchange current `state_sync` snapshots in both directions before the next
  movement: position, robot status, task ID/status, cargo ID/state/owner, original
  destination and current charger claim. Broadcast current position and intent.
- Peers learn these snapshots; they do not use them to mutate authoritative rack
  inventory or take cargo from another robot. Old snapshot/motion versions are
  rejected, and learned custody snapshots expire instead of persisting as truth.

The legacy **Wi-Fi dead zone** buttons call these same loss/reconcile hooks.
Communication and mechanical failure are independent; an offline carrier can
fail, retain its cargo, reconnect with `recovery_pending` custody, and recover.

## Metrics definitions

All counters/times come from actual simulated events, not fabricated benchmarks:

- `robot_failures`: accepted mechanical-failure drills.
- `tasks_reassigned`: existing-auction assignments of failure-associated tasks.
- `cargo_recovered`: completed physical handoff dwells (not merely an award).
- `successful_recoveries`: failure-associated original tasks actually delivered.
- `recovery_times_ticks`: original delivery tick minus failure tick, per resolved
  failure; `avg_recovery_ticks` is empty until a success occurs.
- `communication_loss_events` / `reconciliations`: accepted link loss/restoration.
- Collisions/deadlocks reuse consolidation's real counters; mission completion
  comes from target occupancy. Preparing a new round resets resilience metrics.

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

Coverage includes all previous Phase 1–6 tests, original-task reauction, released/
reacquired reservations, retained carrying custody, adjacent animated handoff,
unchanged destinations, inventory conservation every tick, restoration guards,
local safety, stale connection/snapshot/motion rejection, bidirectional reconcile,
conflict rejection, offline carrier recovery and mission completion in WH1/2/3.

Deterministic full-charge carrying episodes measured:

| Warehouse | Failure tick | Handoff complete | Recovered task delivered | Recovery ticks | Mission filled | Collisions | Deadlocks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| #1 | 19 | 45 | 56 | 37 | 72 | 0 | 0 |
| #2 | 17 | 39 | 50 | 33 | 94 | 0 | 0 |
| #3 | 20 | 49 | 60 | 40 | 166 | 0 | 0 |

These are functional scenario results, not scalability/Phase 8 benchmarks.
Before-pickup episodes also completed all three warehouses with zero collisions/
deadlocks. Real WebSocket tests run each failure case and loss/reconnect separately
in all three warehouses, using unchanged default demo energy levels and checking
inventory on every received frame. They verify healthy fleet parking and restoring
the failed unit without moving its coordinates.

The real production dashboard was also exercised in WH1/2/3 through both failure
cases, communication loss/reconnect, physical handoff, target filling and robot
restoration. All six dashboard mission runs completed with zero collisions and
zero deadlocks. Actual timings depend on the operator's drill point.

## Scope boundary

This is a simulation of stopped-body failure and adjacent custody transfer, not
mechanical repair, towing, collision certification or robotic manipulation control.
No failures are injected during lift/place/handoff dwell. Infeasible recovery keeps
cargo with its authoritative owner and reports pending/blocked work; it does not
teleport cargo, reroute to a fabricated destination or silently discard it.

No ROS2, physical robot control, large-fleet scalability, distributed consensus,
station-outage catalog, or Phase 8 benchmarking was implemented.
