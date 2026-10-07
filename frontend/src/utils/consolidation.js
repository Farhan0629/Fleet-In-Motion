// Pure view model, tested independently from WebGL and WebSocket transport.
export function consolidationView(mission, connected, running) {
  const m = mission || {}
  return {
    canPrepare: Boolean(connected && !running && !m.active),
    canFill: Boolean(connected && !running && m.enabled && !m.started && m.status === 'ready'),
    canResume: Boolean(connected && !running && m.status === 'timed_out'),
    progress: Math.max(0, Math.min(100, m.progress ?? 0)),
    title: m.status === 'completed' ? 'Target rack filled' : (m.status || 'not_prepared').replaceAll('_', ' '),
  }
}
