import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

test('barrier warning renders above controls and clears after recovery', async () => {
  const server = await createServer({
    root: fileURLToPath(new URL('../../', import.meta.url)),
    server: { middlewareMode: true },
    appType: 'custom',
  })
  let snapshot, originalRobots
  try {
    const { default: Dashboard } = await server.ssrLoadModule('/src/dashboard/Dashboard.jsx')
    const { default: store } = await server.ssrLoadModule('/src/store.js')
    // SSR reads Zustand's initial snapshot, not subsequent client updates.
    snapshot = store.getInitialState()
    originalRobots = snapshot.robots
    snapshot.robots = [{ id: 1, name: 'Farhan', battery: 95, x: 16, y: 11,
      status: 'waiting', navigation_message: 'Please remove the barrier',
      navigation_blocked_reason: 'barrier', planned_path: [], task: null }]
    const blocked = renderToStaticMarkup(React.createElement(Dashboard))
    assert(blocked.includes('role="alert" class="sticky'), 'Sticky alert missing')
    assert(blocked.indexOf('Please remove the barrier') < blocked.indexOf('Demonstration controls'))
    snapshot.robots = []
    assert(!renderToStaticMarkup(React.createElement(Dashboard)).includes('Please remove the barrier'))
  } finally {
    if (snapshot) snapshot.robots = originalRobots
    await server.close()
  }
})
