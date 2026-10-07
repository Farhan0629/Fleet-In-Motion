import useStore from '../store'
import { sendCommand } from '../websocket.js'
import { resilienceControls } from '../utils/resilience.js'

export default function ResiliencePanel() {
  const robots = useStore((s) => s.robots)
  const selected = useStore((s) => s.selectedRobotId)
  const selectRobot = useStore((s) => s.selectRobot)
  const connected = useStore((s) => s.connected)
  const sim = useStore((s) => s.sim)
  const tasks = useStore((s) => s.tasks)
  const network = useStore((s) => s.network)
  const robot = robots.find((r) => r.id === selected) || robots[0]
  const offline = (network?.partitioned || []).includes(robot?.id)
  const controls = resilienceControls(robot, tasks.consolidation, sim, connected, offline)
  const metrics = tasks.resilience || {}
  const events = metrics.events || []
  const command = (action) => sendCommand(action, { robot_id: robot.id })
  const button = 'min-h-9 rounded border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-700'
  return <section aria-label="Fleet resilience" className="space-y-2 rounded-lg border border-slate-200 bg-white p-3">
    <h2 className="text-sm font-semibold text-slate-900">Fleet resilience</h2>
    <select aria-label="Resilience robot" value={robot?.id || ''} onChange={(e) => selectRobot(Number(e.target.value))} className="w-full rounded border border-slate-300 bg-white p-2 text-xs">
      {!robots.length && <option value="">Waiting for fleet</option>}
      {robots.map((r) => <option value={r.id} key={r.id}>{r.name || `R${r.id}`}</option>)}
    </select>
    {robot && <p className="text-xs font-semibold text-slate-700">{robot.name} — {robot.failed ? 'FAILED' : offline ? 'NETWORK OFFLINE · local sensing' : robot.status}</p>}
    <div className="grid grid-cols-2 gap-2">
      {controls.canFail && <button type="button" className={button} onClick={() => command('simulate_robot_failure')}>Simulate Robot Failure</button>}
      {controls.canLoseCommunication && <button type="button" className={button} onClick={() => command('simulate_communication_loss')}>Simulate Communication Loss</button>}
      {controls.canRestoreRobot && <button type="button" className={button} onClick={() => command('restore_robot')}>Restore Robot</button>}
      {controls.canRestoreCommunication && <button type="button" className={button} onClick={() => command('restore_communication')}>Restore Communication</button>}
    </div>
    {robot?.failed && robot.has_cargo && <p role="status" className="text-xs text-rose-700">Cargo {robot.task?.cargo_id} — RECOVERY REQUIRED. Restore Robot becomes available after physical handoff.</p>}
    {robot?.handling && <p className="text-xs text-slate-500">Failure drill waits until the physical transfer finishes.</p>}
    {!tasks.consolidation?.started && <p className="text-xs text-slate-500">Prepare inventory and start Fill Empty Rack to run a resilience drill.</p>}
    {events.slice(-3).map((event, index) => <div key={`${event.task_id}-${index}`} className="rounded border border-slate-200 bg-slate-50 p-2 text-[11px] text-slate-700">
      <p>Task #{event.task_id} · Cargo {event.cargo_id} — {event.status.replaceAll('_', ' ').toUpperCase()}</p>
      <p>Original destination: {event.destination}</p>
      <p>Recovery robot: {robots.find((r) => r.id === event.recovery_robot_id)?.name || 'Awaiting auction'}</p>
    </div>)}
    <div className="grid grid-cols-2 gap-1 text-[11px] text-slate-600">
      <span>Robot failures: {metrics.robot_failures ?? 0}</span><span>Successful recoveries: {metrics.successful_recoveries ?? 0}</span>
      <span>Communication losses: {metrics.communication_loss_events ?? 0}</span><span>Reconciliations: {metrics.reconciliations ?? 0}</span>
      <span>Tasks reassigned: {metrics.tasks_reassigned ?? 0}</span><span>Cargo recovered: {metrics.cargo_recovered ?? 0}</span>
      <span>Recovery time: {metrics.avg_recovery_ticks == null ? '—' : `${metrics.avg_recovery_ticks} ticks avg`}</span><span>Mission: {metrics.mission_completed ? 'completed' : 'not completed'}</span>
      <span>Collisions: {metrics.collisions ?? 0}</span><span>Deadlocks: {metrics.deadlocks ?? 0}</span>
    </div>
  </section>
}
