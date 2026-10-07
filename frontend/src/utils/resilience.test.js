import test from 'node:test'
import assert from 'node:assert/strict'
import { resilienceControls } from './resilience.js'
import { mapCargoLifecycle, getRobotStatusMeta, getRobotNextDestination } from './simulationState.js'
import { transferPose, CARRY } from './presentation.js'

test('drill controls are valid only for actual active robot/cargo states', () => {
  const robot = { id: 1, available: true, task: { id: 12 } }
  const mission = { started: true, status: 'running' }
  const sim = { running: true, paused: true }
  assert.equal(resilienceControls(robot, mission, sim, true, false).canFail, true)
  assert.equal(resilienceControls(robot, mission, sim, false, false).canFail, false)
  assert.equal(resilienceControls({ ...robot, handling: {} }, mission, sim, true, false).canFail, false)
  assert.equal(resilienceControls({ ...robot, task: { recovery_required: true } }, mission, sim, true, false).canFail, false)
  assert.equal(resilienceControls(robot, { started: true, status: 'completed' }, sim, true, false).canFail, false)
  const failed = { ...robot, failed: true, available: false, has_cargo: true }
  assert.equal(resilienceControls(failed, mission, sim, true, false).canRestoreRobot, false)
  assert.equal(resilienceControls({ ...failed, has_cargo: false, task: null }, mission, sim, true, false).canRestoreRobot, true)
  assert.equal(resilienceControls(robot, mission, sim, true, true).canRestoreCommunication, true)
  assert.equal(resilienceControls(robot, mission, sim, true, true).canLoseCommunication, false)
})

test('physical handoff retains one rendered carton and uses the actual failed carry pose', () => {
  const task = { id: 12, cargo_id: 'C017', recovery_required: true, pickup_kind: 'recovery', failed_robot_id: 1, pickup: [4, 5] }
  const failed = { id: 1, failed: true, has_cargo: true, task }
  const receiver = { id: 2, has_cargo: false, task }
  let state = mapCargoLifecycle({}, [failed, receiver], { racks: [] })
  assert.equal(state.carryingCargo.length, 1)
  assert.equal(state.carryingCargo[0].taskId, 'C017')
  const handling = { kind: 'pickup', place: 'recovery', task_id: 12, cargo_id: 'C017', handoff_station: [-.35, 1.04, 1] }
  state = mapCargoLifecycle({}, [{ ...failed, has_cargo: false, task: null }, { ...receiver, handling }], { racks: [] })
  assert.equal(state.carryingCargo.length, 0)
  assert.equal(state.handlingCargo.length, 1)
  assert.equal(state.handlingCargo[0].cargoId, 'C017')
  assert.deepEqual(transferPose({ ...handling, progress: 0 }).position, handling.handoff_station)
  assert.deepEqual(transferPose({ ...handling, progress: 1 }).position, [...CARRY])
  assert.notDeepEqual(transferPose({ ...handling, progress: .5 }).position, handling.handoff_station)
  assert.match(getRobotStatusMeta(failed).label, /Failed/)
  assert.match(getRobotStatusMeta({ handling }).label, /handoff/)
  assert.equal(getRobotNextDestination(receiver).type, 'RECOVERY · robot 1')
})
