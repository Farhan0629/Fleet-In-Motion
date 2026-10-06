import test from 'node:test'
import assert from 'node:assert/strict'
import { getMissionSummary, getRobotNextDestination, getRobotStatusMeta, mapCargoLifecycle } from './simulationState.js'

const floor = {
  tables: [
    { id: 0, code: 'T01', cell: [2, 2], side: 'west', state: 'loaded', task_id: 1 },
    { id: 1, code: 'T02', cell: [2, 5], side: 'west', state: 'empty', task_id: null },
    { id: 6, code: 'T07', cell: [16, 2], side: 'east', state: 'loaded', task_id: 3 },
  ],
  racks: [
    { id: 0, code: 'A1-01', cell: [5, 3], access: [4, 3], state: 'stored', task_id: 2 },
    { id: 1, code: 'A1-02', cell: [6, 3], access: [7, 3], state: 'reserved', task_id: 3 },
    { id: 2, code: 'A1-03', cell: [5, 4], access: [4, 4], state: 'empty', task_id: null },
  ],
}

test('a carton is drawn on its table only while the backend says the table is loaded', () => {
  const state = mapCargoLifecycle({}, [], floor)
  assert.deepEqual(state.tableCargo.map((item) => item.taskId), [1, 3])
  assert.deepEqual(state.storedCargo.map((item) => item.code), ['A1-01'])
})

test('a carton mid-transfer belongs to the robot, never to the table or the slot', () => {
  const robots = [{ id: 1, has_cargo: false, handling: { task_id: 1, kind: 'pickup', place: 'table', station: [2, 2] } }]
  const state = mapCargoLifecycle({}, robots, floor)
  assert.deepEqual(state.tableCargo.map((item) => item.taskId), [3])
  assert.equal(state.handlingCargo.length, 1)
  assert.equal(state.carryingCargo.length, 0)
})

test('a stored carton is hidden from the slot while a robot is reaching into it', () => {
  const robots = [{ id: 2, has_cargo: false, handling: { task_id: 2, kind: 'pickup', place: 'rack', station: [4, 3] } }]
  const state = mapCargoLifecycle({}, robots, floor)
  assert.equal(state.storedCargo.length, 0)
})

test('a carried carton follows the robot, not the queue', () => {
  const robots = [{ id: 3, has_cargo: true, task: { id: 5, dropoff: [4, 9], slot_code: 'B1-01' } }]
  const state = mapCargoLifecycle({}, robots, floor)
  assert.deepEqual(state.carryingCargo, [{ taskId: 5, robotId: 3, dropoff: [4, 9], slotCode: 'B1-01' }])
})

test('status copy reads as a putaway round', () => {
  assert.equal(getRobotStatusMeta({ status: 'moving_to_dropoff', has_cargo: true }).label, 'Carrying to rack')
  assert.equal(getRobotStatusMeta({ handling: { kind: 'dropoff', place: 'rack' } }).label, 'Storing in rack')
  assert.equal(getRobotStatusMeta({ status: 'charging', has_cargo: false }).label, 'Charging')
  assert.equal(getRobotStatusMeta({ status: 'idle', parked: true }).label, 'Parked \u00b7 charged')
})

test('next stop names the table it is collecting from and the slot it is filling', () => {
  assert.deepEqual(getRobotNextDestination({ status: 'moving_to_pickup', task: { pickup: [2, 5], dropoff: [4, 3], pickup_kind: 'table', dropoff_kind: 'rack', table_code: 'T02', slot_code: 'A1-01' } }), { type: 'TABLE T02', coordinate: [2, 5] })
  assert.deepEqual(getRobotNextDestination({ status: 'moving_to_dropoff', has_cargo: true, task: { pickup: [2, 5], dropoff: [4, 3], pickup_kind: 'table', dropoff_kind: 'rack', table_code: 'T02', slot_code: 'A1-01' } }), { type: 'RACK A1-01', coordinate: [4, 3] })
  assert.deepEqual(getRobotNextDestination({ status: 'idle', parked: true, charger: [1, 1] }), { type: 'PARKED', coordinate: [1, 1] })
})

test('mission summary reports the round, not a two-leg cycle', () => {
  const mission = getMissionSummary({ total_count: 12, completed_count: 5, pending: [{}, {}], active: [{}], stored_count: 5, in_racks: 5, tables_loaded: 7 })
  assert.deepEqual(mission, { total: 12, completed: 5, active: 1, pending: 2, stored: 5, inRacks: 5, tablesLoaded: 7, progress: 42 })
})

test('barrier warning takes precedence over carrying status and clears with telemetry', () => {
  assert.equal(getRobotStatusMeta({ status: 'waiting', has_cargo: true, navigation_message: 'Please remove the barrier' }).label, 'Please remove the barrier')
  assert.equal(getRobotStatusMeta({ status: 'moving_to_dropoff', has_cargo: true, navigation_message: null }).label, 'Carrying to rack')
})

test('a barrier-blocked charging unit still displays its claimed pad destination', () => {
  assert.deepEqual(getRobotNextDestination({ status: 'waiting', charger: [1, 1], task: null, planned_path: [] }), { type: 'CHARGING', coordinate: [1, 1] })
})
