import test from 'node:test'
import assert from 'node:assert/strict'
import { consolidationView } from './consolidation.js'
import { mapCargoLifecycle, getRobotNextDestination } from './simulationState.js'

test('controls require explicit setup; prevent duplicate starts and support safe resume', () => {
  assert.equal(consolidationView({}, true, false).canFill, false)
  assert.equal(consolidationView({ enabled: true, status: 'ready' }, true, false).canFill, true)
  assert.equal(consolidationView({ enabled: true, status: 'ready' }, false, false).canFill, false)
  assert.equal(consolidationView({ enabled: true, started: true, status: 'running' }, true, true).canFill, false)
  assert.equal(consolidationView({ active: 1 }, true, false).canPrepare, false)
  assert.equal(consolidationView({ status: 'timed_out' }, true, false).canResume, true)
  assert.equal(consolidationView({ status: 'completed', progress: 100 }, true, false).title, 'Target rack filled')
})

test('stable carton identity through source, handling, carrying and destination', () => {
  const task = { id: 71, cargo_id: 'C017', pickup: [1, 2], dropoff: [5, 6], pickup_kind: 'rack', dropoff_kind: 'rack', pickup_slot_code: 'B4', dropoff_slot_code: 'C1' }
  const source = { state: 'stored', cargo_id: 'C017', task_id: 71, code: 'B4', cell: [2, 2], access: [1, 2] }
  let view = mapCargoLifecycle({}, [], { racks: [source] })
  assert.equal(view.storedCargo[0].taskId, 'C017')
  const handling = { kind: 'pickup', task_id: 71, cargo_id: 'C017' }
  view = mapCargoLifecycle({}, [{ id: 1, task, handling }], { racks: [{ ...source, state: 'empty' }] })
  assert.equal(view.storedCargo.length, 0)
  assert.equal(view.handlingCargo[0].cargoId, 'C017')
  view = mapCargoLifecycle({}, [{ id: 1, has_cargo: true, task }], { racks: [] })
  assert.equal(view.carryingCargo[0].taskId, 'C017')
  view = mapCargoLifecycle({}, [], { racks: [{ ...source, task_id: null, code: 'C1' }] })
  assert.equal(view.storedCargo[0].taskId, 'C017')
  assert.equal(getRobotNextDestination({ task }).type, 'RACK B4')
  assert.equal(getRobotNextDestination({ task, has_cargo: true }).type, 'RACK C1')
})
