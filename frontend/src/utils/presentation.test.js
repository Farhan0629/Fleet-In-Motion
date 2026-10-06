import test from 'node:test'
import assert from 'node:assert/strict'
import { RIG, CARRY, STATION, CARTON_SIZE, RACK_DECK_LEVELS, RACK_DECK_THICKNESS, rackCartonCenterY, rackSlotWorldPosition, headingToYaw, angleDelta, createMotion, queueMotion, advanceMotion, transferPose, chooseFollowRobot } from './presentation.js'
import { getRobotStatusMeta, mapCargoLifecycle, getRobotNextDestination } from './simulationState.js'
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-8, `${a} != ${b}`)
test('rig chest is below head and above hips in a single coordinate space', () => {
  assert.ok(RIG.hip < RIG.chest && RIG.chest < RIG.shoulder && RIG.shoulder < RIG.head)
  assert.ok(RIG.hip - RIG.upperLeg - RIG.lowerLeg > 0)
})
test('all four backend headings match the +Z-facing model', () => {
  for (const [heading, x, z] of [[0, 1, 0], [90, 0, 1], [180, -1, 0], [270, 0, -1]]) {
    near(Math.sin(headingToYaw(heading)), x); near(Math.cos(headingToYaw(heading)), z)
  }
})
test('heading wraps along the shortest turn', () => near(angleDelta(Math.PI - 0.1, -Math.PI + 0.1), 0.2))
test('new network target does not recreate or snap the current position', () => {
  const m = createMotion(1.5, 1.5)
  queueMotion(m, 2.5, 1.5, 0.2)
  near(m.x, 1.5); advanceMotion(m, 0.1); near(m.x, 2)
  advanceMotion(m, 0.1); near(m.x, 2.5)
})
test('queued right-angle turns traverse each axis without corner cutting', () => {
  const m = createMotion(1.5, 1.5)
  queueMotion(m, 2.5, 1.5, 0.2); queueMotion(m, 2.5, 2.5, 0.2)
  advanceMotion(m, 0.1); near(m.x, 2); near(m.z, 1.5)
  advanceMotion(m, 0.1); near(m.x, 2.5); near(m.z, 1.5)
  advanceMotion(m, 0.1); near(m.x, 2.5); near(m.z, 2)
})
test('pause freezes the position; resume continues the same segment', () => {
  const m = createMotion(0, 0); queueMotion(m, 1, 0)
  advanceMotion(m, 0.1, true); near(m.x, 0)
  advanceMotion(m, 0.1); near(m.x, 0.5)
})
test('reset and reduced motion snap instead of sweeping across racks', () => {
  const m = createMotion(1, 1); queueMotion(m, 17, 9)
  near(m.x, 17); assert.equal(m.queue.length, 0)
  queueMotion(m, 18, 9, 0.2, true); near(m.x, 18)
})
test('pickup and dropoff positions meet the same station and hand endpoints', () => {
  assert.deepEqual(transferPose({ kind: 'pickup', progress: 0 }).position, [...STATION])
  assert.deepEqual(transferPose({ kind: 'pickup', progress: 1 }).position, [...CARRY])
  assert.deepEqual(transferPose({ kind: 'dropoff', progress: 0 }).position, [...CARRY])
  assert.deepEqual(transferPose({ kind: 'dropoff', progress: 1 }).position, [...STATION])
})
test('rack-slot placement rests every carton on the selected deck', () => {
  const slots = [
    { cell: [3, 3], island: 'Rack A' },
    { cell: [20, 3], island: 'Rack B' },
    { cell: [3, 12], island: 'Rack C' },
    { cell: [25, 12], island: 'Rack D' },
  ]
  const expectedY = RACK_DECK_LEVELS.lowRack[0] + RACK_DECK_THICKNESS / 2 + CARTON_SIZE[1] / 2
  near(rackCartonCenterY('lowRack'), expectedY)
  for (const slot of slots) {
    assert.deepEqual(rackSlotWorldPosition(slot, 'lowRack'), [slot.cell[0] + 0.5, expectedY, slot.cell[1] + 0.5])
  }
})
test('follow respects current selection, and handles an empty fleet', () => {
  const robots = [{ id: 1 }, { id: 2 }]
  assert.equal(chooseFollowRobot(robots, 2, 1).id, 2)
  assert.equal(chooseFollowRobot(robots, null, null).id, 1)
  assert.equal(chooseFollowRobot([], null, null), null)
})
test('safety and handling labels are not hidden by cargo', () => {
  assert.equal(getRobotStatusMeta({ has_cargo: true, status: 'yielding' }).label, 'Yielding')
  assert.equal(getRobotStatusMeta({ has_cargo: true, handling: { kind: 'dropoff' } }).label, 'Placing carton')
})
test('a carton in transfer is represented exactly once, and only by the robot', () => {
  const task = { id: 7, pickup: [2, 5], dropoff: [4, 3], table_code: 'T02', slot_code: 'A1-01' }
  const floor = {
    tables: [{ code: 'T02', cell: [2, 5], side: 'west', state: 'loaded', task_id: 7 }],
    racks: [{ id: 0, code: 'A1-01', cell: [5, 3], access: [4, 3], state: 'reserved', task_id: 7 }],
  }
  const robot = { id: 1, task, has_cargo: true, handling: { kind: 'dropoff', task_id: 7, place: 'rack' } }
  const state = mapCargoLifecycle({ active: [task] }, [robot], floor)
  assert.equal(state.tableCargo.length + state.carryingCargo.length + state.storedCargo.length, 0)
  assert.equal(state.handlingCargo.length, 1)
  const stored = mapCargoLifecycle({}, [{ id: 1, has_cargo: false }], {
    tables: [{ code: 'T02', cell: [2, 5], side: 'west', state: 'empty', task_id: null }],
    racks: [{ id: 0, code: 'A1-01', cell: [5, 3], access: [4, 3], state: 'stored', task_id: 7 }],
  })
  assert.equal(stored.storedCargo.length, 1)
  assert.equal(stored.tableCargo.length, 0)
})
test('charging destination is drawn from the actual route', () => {
  assert.deepEqual(getRobotNextDestination({ status: 'moving_to_charge', planned_path: [[3, 18], [1, 18]] }), { type: 'CHARGING', coordinate: [1, 18] })
})
