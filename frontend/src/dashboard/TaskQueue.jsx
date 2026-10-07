import useStore from '../store'
import { sendCommand } from '../websocket.js'
import { consolidationView } from '../utils/consolidation.js'

function TaskRow({ task, robots }) {
  const owner = robots.find((r) => r.id === task.assigned_to)
  return <div className="rounded border border-slate-200 bg-slate-50 p-2 text-xs text-slate-700">
    <div className="flex justify-between gap-2 font-semibold">
      <span>{task.cargo_id || `PKG-${task.id}`} · Task #{task.id}</span>
      <span>{owner?.name || task.status}</span>
    </div>
    <p className="mt-1 font-mono text-[11px]">{task.source_label || task.table_code || 'Loading'} → {task.destination_label || task.slot_code || 'Delivery'}</p>
    {task.stage === 'consolidation' && <p className="mt-1 text-[10px] text-slate-500">{task.status === 'completed' ? 'Placed in rack' : task.picked_up ? 'Pickup complete · transporting / placing' : task.status}</p>}
    {task.failure_reason && <p className="mt-1 text-rose-700">{task.failure_reason}</p>}
    {task.stage === 'consolidation' && ['pending', 'assigned'].includes(task.status) && !task.picked_up && <button type="button" onClick={() => sendCommand('cancel_task', { task_id: task.id })} className="mt-2 rounded border border-rose-300 px-2 py-1 text-[10px] text-rose-700">Cancel relocation</button>}
  </div>
}

export default function TaskQueue() {
  const tasks = useStore((s) => s.tasks)
  const robots = useStore((s) => s.robots)
  const sim = useStore((s) => s.sim)
  const connected = useStore((s) => s.connected)
  const error = useStore((s) => s.connectionError)
  const mission = tasks.consolidation || {}
  const view = consolidationView(mission, connected, sim.running)
  const rows = [...(tasks.active || []), ...(tasks.pending || []), ...(tasks.failed || []), ...(tasks.cancelled || []), ...(tasks.completed || [])]
  return <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-3">
    <h2 className="text-sm font-semibold text-slate-900">Dynamic rack consolidation</h2>
    <div className="space-y-2 rounded border border-blue-200 bg-blue-50 p-2 text-xs">
      <p className="text-slate-600">Setup loads stored cartons and leaves the designated target empty using warehouse data. It replaces the stopped demonstration, not a running mission.</p>
      <div className="flex gap-2">
        <button type="button" disabled={!view.canPrepare} onClick={() => sendCommand('prepare_consolidation')} className="rounded border border-blue-300 bg-white px-2 py-2 disabled:opacity-50">Prepare inventory</button>
        <button type="button" disabled={!view.canFill} onClick={() => sendCommand('fill_empty_rack')} className="flex-1 rounded bg-blue-600 px-3 py-2 font-semibold text-white disabled:opacity-50">Fill Empty Rack</button>
      </div>
      {view.canResume && <button type="button" onClick={() => sendCommand('resume_consolidation')} className="rounded border border-blue-300 bg-white p-2">Resume retained mission</button>}
      <p className="font-semibold capitalize" role="status">{view.title}</p>
      <p>{mission.message}</p>
      <p>Target rack: <strong>{mission.target_rack || 'Not configured'}</strong> · {mission.filled_slots ?? 0}/{mission.capacity ?? 0} slots</p>
      {mission.enabled && <>
        <div className="grid grid-cols-2 gap-1 text-slate-700">
          <span>Available sources: {mission.available_source_cartons ?? 0}</span><span>Generated: {mission.tasks_generated ?? 0}</span>
          <span>Pending: {mission.pending ?? 0}</span><span>Active: {mission.active ?? 0}</span>
          <span>Completed: {mission.completed ?? 0}</span><span>Progress: {view.progress}%</span>
        </div>
        <progress aria-label="Consolidation progress" value={view.progress} max="100" className="h-2 w-full" />
        <p>Robots used: {(mission.robots_used || []).map((id) => robots.find((r) => r.id === id)?.name || `R${id}`).join(', ') || 'None'}</p>
        <p>Collisions: {mission.collision_count ?? 0} · Deadlocks: {mission.deadlock_count ?? 0}</p>
      </>}
    </div>
    {error && <p role="alert" className="text-xs text-rose-700">{error}</p>}
    <div className="flex justify-between text-xs"><h3 className="font-semibold">Task queue</h3><span>{tasks.completed_count ?? 0}/{tasks.total_count ?? 0} completed</span></div>
    {!mission.enabled && <p className="text-xs text-slate-500">Existing demonstration: RECEIVE → PUTAWAY → STORE. Use Start demonstration to run it.</p>}
    <div className="max-h-64 space-y-2 overflow-y-auto">
      {rows.map((task) => <TaskRow key={task.id} task={task} robots={robots} />)}
      {!rows.length && <p className="py-3 text-center text-xs text-slate-500">No generated tasks yet.</p>}
    </div>
  </section>
}
