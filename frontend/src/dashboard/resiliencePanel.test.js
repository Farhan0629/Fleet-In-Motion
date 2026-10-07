import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

test('resilience dashboard renders recovery custody and only valid restore controls', async () => {
  const server = await createServer({ root: fileURLToPath(new URL('../../', import.meta.url)), server: { middlewareMode: true }, appType: 'custom' })
  let initial, saved
  try {
    const { default: Panel } = await server.ssrLoadModule('/src/dashboard/ResiliencePanel.jsx')
    const { default: store } = await server.ssrLoadModule('/src/store.js')
    initial = store.getInitialState()
    saved = { robots: initial.robots, tasks: initial.tasks, selectedRobotId: initial.selectedRobotId, connected: initial.connected, sim: initial.sim, network: initial.network }
    Object.assign(initial, { connected: true, sim: { running: true }, selectedRobotId: 1,
      robots: [{ id: 1, name: 'Farhan', failed: true, available: false, has_cargo: true, task: { cargo_id: 'C017' } }, { id: 2, name: 'Gaurav' }],
      tasks: { consolidation: { started: true, status: 'recovering' }, resilience: { events: [{ task_id: 12, cargo_id: 'C017', status: 'recovery_pending', recovery_robot_id: 2, destination: 'C1' }] } }, network: { partitioned: [1] } })
    const html = renderToStaticMarkup(React.createElement(Panel))
    assert(html.includes('RECOVERY REQUIRED'))
    assert(html.includes('RECOVERY PENDING'))
    assert(html.includes('Recovery robot: Gaurav'))
    assert(html.includes('Restore Communication'))
    assert(!html.includes('>Restore Robot</button>'))
    assert(!html.includes('>Simulate Robot Failure</button>'))
    initial.robots[0] = { ...initial.robots[0], has_cargo: false, task: null }
    assert(renderToStaticMarkup(React.createElement(Panel)).includes('>Restore Robot</button>'))
  } finally {
    if (initial) Object.assign(initial, saved)
    await server.close()
  }
})
