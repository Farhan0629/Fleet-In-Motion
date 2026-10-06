import { Component, useEffect, useState } from 'react'
import { connectWebSocket } from './websocket'
import useStore from './store'
import Scene from './components/Scene'
import Dashboard from './dashboard/Dashboard'
import RobotPovOverlay from './components/RobotPovOverlay'
class SceneBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    if (this.state.failed) return <div className="scene-message" role="alert"><h2>3D view unavailable</h2><p>The live controls and task panels still work. Try a browser with WebGL enabled.</p><button onClick={() => this.setState({ failed: false })}>Retry 3D view</button></div>
    return this.props.children
  }
}
export default function App() {
  const connected = useStore((s) => s.connected)
  const connectionError = useStore((s) => s.connectionError)
  const setReduced = useStore((s) => s.setReducedMotion)
  const sim = useStore((s) => s.sim)
  const [help, setHelp] = useState(true)
  useEffect(() => connectWebSocket(), [])
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const apply = () => setReduced(media.matches)
    apply(); media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [setReduced])
  return <div className="demo-shell">
    <header className="demo-header">
      <div><p className="eyebrow">SIH 26123 · Warehouse intelligence</p><h1>Fleet in motion<span>Digital twin</span></h1></div>
      <div className={`connection-badge ${connected ? 'online' : ''}`} role="status"><span aria-hidden="true">●</span> {connected ? (sim.running ? sim.paused ? 'Connected · Paused' : 'Connected · Running' : 'Connected · Ready') : 'Offline · Reconnecting'}</div>
    </header>
    <main className="demo-layout">
      <section className="demo-viewport relative" aria-label="Interactive warehouse digital twin">
        <SceneBoundary><Scene /></SceneBoundary>
        <RobotPovOverlay />
        {help && <div className="watch-guide"><div><strong>Watch a carton move</strong><p>All twelve tables start with one carton; the racks start empty. Select a unit, choose Follow, and watch it lift the carton off a table, carry it and slide it into its reserved rack slot — the table stays empty afterwards. When the last carton is stored, the fleet books charge pads over the mesh and docks. Press "Force high battery" to instantly max out a unit's charge.</p></div><button aria-label="Dismiss viewing guide" onClick={() => setHelp(false)}>×</button></div>}
        {connectionError && connected && <div className="connection-notice" role="status">{connectionError}</div>}
        {!connected && <div className="connection-notice" role="status">{connectionError || 'Waiting for the simulation server on port 8000. No live values are fabricated.'}</div>}
        <div className="viewport-caption"><span>RECEIVE → PUTAWAY → STORE · then DOCK → CHARGE</span><span>Drag to orbit · Scroll to zoom</span></div>
      </section>
      <aside className="demo-dashboard" aria-label="Fleet controls and telemetry"><Dashboard /></aside>
    </main>
  </div>
}
