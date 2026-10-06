import { useEffect } from 'react'
import { sendCommand } from '../websocket'
import useStore from '../store'

const BUTTON = 'min-h-11 rounded-md border px-3 text-sm font-medium transition'
const WAREHOUSES = [
  { id: 'warehouse_1', label: 'WH #1', detail: 'Standard 20×20' },
  { id: 'warehouse_2', label: 'WH #2', detail: 'Smart Hub 28×16' },
  { id: 'warehouse_3', label: 'WH #3', detail: 'ASRS Campus 36×24' },
]

export default function Controls() {
  const connected = useStore((s) => s.connected)
  const sim = useStore((s) => s.sim)
  const robots = useStore((s) => s.robots)
  const network = useStore((s) => s.network)
  const warehouse = useStore((s) => s.warehouse)
  const cameraMode = useStore((s) => s.cameraMode)
  const setCameraMode = useStore((s) => s.setCameraMode)
  const showRoutes = useStore((s) => s.showRoutes)
  const showP2P = useStore((s) => s.showP2P)
  const setShowRoutes = useStore((s) => s.setShowRoutes)
  const setShowP2P = useStore((s) => s.setShowP2P)
  const shelfView = useStore((s) => s.shelfView)
  const setShelfView = useStore((s) => s.setShelfView)
  const placeMode = useStore((s) => s.placeMode)
  const setPlaceMode = useStore((s) => s.setPlaceMode)

  const partitioned = network?.partitioned ?? []
  const blockedCount = warehouse?.blocked?.length ?? 0
  // Barriers may only be edited while the floor is still: paused, or not
  // started yet. The server enforces the same rule.
  const canEditBlocks = !sim.running || sim.paused

  useEffect(() => {
    if (!canEditBlocks && placeMode) setPlaceMode(false)
  }, [canEditBlocks, placeMode, setPlaceMode])

  const sendSafe = (action, params) => {
    if (!connected) return
    sendCommand(action, params)
  }

  return (
    <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-3">
      <div className="space-y-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Facility Topology</p>
        <div className="grid grid-cols-3 gap-2">
          {WAREHOUSES.map((facility) => {
            const active = warehouse?.id === facility.id || (!warehouse?.id && facility.id === 'warehouse_1' && warehouse?.width === 20)
            return <button
              key={facility.id}
              type="button"
              disabled={!connected || (sim.running && !sim.paused)}
              onClick={() => sendSafe('switch_warehouse', { warehouse_id: facility.id })}
              className={`${BUTTON} px-2 text-xs ${active ? 'border-indigo-500 bg-indigo-50 text-indigo-700 font-semibold' : 'border-slate-300 bg-slate-50 text-slate-800'}`}
            >
              <span className="block">{facility.label}</span>
              <span className="block text-[10px] font-normal leading-tight">{facility.detail}</span>
            </button>
          })}
        </div>
      </div>

      <h2 className="text-sm font-semibold text-slate-900">Demonstration controls</h2>

      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          disabled={!connected}
          onClick={() => sendSafe('start')}
          className={`${BUTTON} ${sim.running && !sim.paused ? 'border-emerald-400 bg-emerald-600 text-white' : 'border-slate-300 bg-slate-50 text-slate-900'} disabled:cursor-not-allowed disabled:opacity-50`}
        >
          Start demonstration
        </button>
        <button
          type="button"
          disabled={!connected || !sim.running}
          onClick={() => sendSafe('pause')}
          className={`${BUTTON} border-slate-300 bg-slate-50 text-slate-900 disabled:cursor-not-allowed disabled:opacity-50`}
        >
          {sim.paused ? 'Resume' : 'Pause'}
        </button>
      </div>

      <div className="space-y-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Playback speed</p>
        <div className="grid grid-cols-4 gap-2">
          {[0.25, 0.5, 1, 2].map((speed) => (
            <button
              key={speed}
              type="button"
              disabled={!connected}
              onClick={() => sendSafe('speed', { value: speed })}
              className={`${BUTTON} ${sim.speed === speed ? 'border-blue-500 bg-blue-600 text-white' : 'border-slate-300 bg-slate-50 text-slate-800'} disabled:cursor-not-allowed disabled:opacity-50`}
            >
              {speed}x
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-1 rounded-md border border-amber-200 bg-amber-50/60 p-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Disruption drills</p>
        <p className="text-[11px] leading-snug text-slate-600">
          {canEditBlocks
            ? placeMode
              ? 'Placing barriers: drag across the floor to close cells, drag over a barrier to reopen it. Camera rotation is held while placing.'
              : 'Pick “Place barriers” and draw blockages straight onto the floor, then resume and watch the fleet re-route around them.'
            : 'Pause the demonstration to place or remove barriers. Radio dead zones and the battery drill can be triggered at any time.'}
        </p>
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            disabled={!connected || !canEditBlocks}
            aria-pressed={placeMode}
            onClick={() => setPlaceMode(!placeMode)}
            className={`${BUTTON} ${placeMode ? 'border-amber-500 bg-amber-600 text-white' : 'border-amber-400 bg-white text-amber-800'} disabled:cursor-not-allowed disabled:opacity-50`}
          >
            {placeMode ? 'Done placing' : 'Place barriers'}
          </button>
          <button
            type="button"
            disabled={!connected || blockedCount === 0}
            onClick={() => sendSafe('clear_blocks')}
            className={`${BUTTON} border-slate-300 bg-slate-50 text-slate-800 disabled:cursor-not-allowed disabled:opacity-50`}
          >
            Clear blockages{blockedCount ? ` (${blockedCount})` : ''}
          </button>
        </div>
        <button
          type="button"
          disabled={!connected || !canEditBlocks}
          onClick={() => sendSafe('block_aisle')}
          className={`${BUTTON} w-full border-amber-300 bg-white text-amber-800 disabled:cursor-not-allowed disabled:opacity-50`}
          title="Let the server pick a cell on a unit's own planned route"
        >
          Auto-block a route
        </button>
        <p className="pt-1 text-[11px] font-semibold uppercase tracking-wide text-amber-700">Wi-Fi dead zone</p>
        <div className="grid grid-cols-3 gap-2">
          {robots.map((robot) => {
            const offline = partitioned.includes(robot.id)
            const label = robot.name || `UNIT ${String(robot.id).padStart(2, '0')}`
            return (
              <button
                key={robot.id}
                type="button"
                disabled={!connected}
                aria-pressed={offline}
                onClick={() => sendSafe('toggle_partition', { robot_id: robot.id })}
                className={`${BUTTON} truncate px-2 ${offline ? 'border-rose-500 bg-rose-600 text-white' : 'border-slate-300 bg-slate-50 text-slate-800'} disabled:cursor-not-allowed disabled:opacity-50`}
                title={offline ? `${label} radio offline - tap to reconnect` : `Cut ${label}'s radio link`}
              >
                {offline ? `${label} ✕` : label}
              </button>
            )
          })}
          {!robots.length && <p className="col-span-3 text-[11px] text-slate-500">Waiting for fleet state.</p>}
        </div>
        {/* Energy boost. Instantly max out a unit's battery to 100%. */}
        <p className="pt-1 text-[11px] font-semibold uppercase tracking-wide text-emerald-700">Force high battery</p>
        <div className="grid grid-cols-3 gap-2">
          {robots.map((robot) => {
            const label = robot.name || `UNIT ${String(robot.id).padStart(2, '0')}`
            const full = robot.battery >= 100
            return (
              <button
                key={robot.id}
                type="button"
                disabled={!connected || full}
                onClick={() => sendSafe('boost_battery', { robot_id: robot.id })}
                className={`${BUTTON} truncate px-2 ${full ? 'border-emerald-500 bg-emerald-50 text-emerald-700' : 'border-slate-300 bg-slate-50 text-slate-800'} disabled:cursor-not-allowed disabled:opacity-60`}
                title={full ? `${label} is already at 100%` : `Boost ${label} to full charge`}
              >
                {full ? `${label} ⚡` : `${label} ${Math.round(robot.battery)}%`}
              </button>
            )
          })}
          {!robots.length && <p className="col-span-3 text-[11px] text-slate-500">Waiting for fleet state.</p>}
        </div>
      </div>

      <div className="space-y-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Camera presets</p>
        <div className="grid grid-cols-2 gap-2">
          {[
            ['overview', 'Overview'],
            ['topdown', 'Top-down'],
            ['follow', 'Follow selected'],
            ['pov', "Robot's POV"],
            ['orbit', 'Manual orbit'],
          ].map(([mode, label]) => (
            <button
              key={mode}
              type="button"
              onClick={() => setCameraMode(mode)}
              className={`${BUTTON} ${mode === 'orbit' ? 'col-span-2' : ''} ${cameraMode === mode ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-slate-300 bg-slate-50 text-slate-800'}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Visibility</p>
        <div className="grid grid-cols-3 gap-2">
          {[
            ['solid', 'Full racks'],
            ['xray', 'X-ray racks'],
            ['lowRack', 'Low-rack'],
          ].map(([mode, label]) => (
            <button
              key={mode}
              type="button"
              onClick={() => setShelfView(mode)}
              className={`${BUTTON} ${shelfView === mode ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-slate-300 bg-slate-50 text-slate-800'}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={() => setShowRoutes(!showRoutes)}
          className={`${BUTTON} ${showRoutes ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-slate-300 bg-slate-50 text-slate-800'}`}
        >
          {showRoutes ? 'Hide routes' : 'Show routes'}
        </button>
        <button
          type="button"
          onClick={() => setShowP2P(!showP2P)}
          className={`${BUTTON} ${showP2P ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-slate-300 bg-slate-50 text-slate-800'}`}
        >
          {showP2P ? 'Hide P2P' : 'Show P2P'}
        </button>
      </div>
    </section>
  )
}
