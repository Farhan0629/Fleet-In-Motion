import useStore from '../store'
import { useMemo, useState } from 'react'
import { sendCommand } from '../websocket.js'

// One carton, one leg: table -> rack slot. A package id appears exactly once in
// this queue and exactly once in the completed count, so nothing on screen can
// be mistaken for a second job invented mid-round.
const STAGE = {
  putaway: { label: 'Putaway', className: 'bg-violet-100 text-violet-700' },
  direct: { label: 'Direct', className: 'bg-slate-100 text-slate-600' },
  dynamic: { label: 'Dynamic', className: 'bg-blue-100 text-blue-700' },
}

function TaskRow({ task, state, destinations }) {
  const stage = STAGE[task.stage] || STAGE.direct
  const from = task.source_label || task.pickup_slot_code || task.table_code || `R(${task.pickup[0]},${task.pickup[1]})`
  const to = task.destination_label || task.dropoff_slot_code || (task.dropoff_kind === 'rack' ? task.slot_code : `D(${task.dropoff[0]},${task.dropoff[1]})`)
  const [destination, setDestination] = useState(task.destination_ref || '')
  return (
    <div className="rounded border border-slate-200 bg-slate-50 px-2 py-2 text-xs text-slate-700">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 font-semibold text-slate-900">
          PKG-{String(task.id).padStart(3, '0')}
          <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase ${stage.className}`}>{stage.label}</span>
        </span>
        <span className="rounded bg-white px-1.5 py-0.5 text-[10px] font-medium uppercase text-slate-500">{state}</span>
      </div>
      <p className="mt-1 font-mono text-[11px]">{from} → {to}</p>
      <p className="mt-1 text-[10px] text-slate-500">Priority {task.priority ?? 3}{task.retry_count ? ` · retry ${task.retry_count}/${task.max_retries}` : ''}</p>
      {state === 'pending' && task.dynamic && (
        <div className="mt-2 flex gap-1">
          <select aria-label={`Destination for task ${task.id}`} value={destination} onChange={(event) => setDestination(event.target.value)} className="min-w-0 flex-1 rounded border border-slate-300 bg-white px-1 py-1 text-[10px]">
            {destinations.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
          <button type="button" onClick={() => sendCommand('update_task_destination', { task_id: task.id, destination })} className="rounded border border-slate-300 px-2 text-[10px]">Change</button>
        </div>
      )}
      {task.dynamic && state !== 'completed' && (
        <div className="mt-2 flex gap-1">
          {state !== 'pending' && <button type="button" onClick={() => sendCommand('reassign_task', { task_id: task.id })} className="rounded border border-blue-300 px-2 py-1 text-[10px] text-blue-700">Reassign</button>}
          <button type="button" onClick={() => sendCommand('cancel_task', { task_id: task.id })} className="rounded border border-rose-300 px-2 py-1 text-[10px] text-rose-700">Cancel</button>
        </div>
      )}
      {(state === 'cancelled' || state === 'failed') && task.retry_count < task.max_retries && (
        <button type="button" onClick={() => sendCommand('retry_task', { task_id: task.id })} className="mt-2 rounded border border-amber-300 px-2 py-1 text-[10px] text-amber-700">Retry</button>
      )}
    </div>
  )
}

export default function TaskQueue() {
  const tasks = useStore((s) => s.tasks)
  const robots = useStore((s) => s.robots)
  const warehouse = useStore((s) => s.warehouse)
  const locations = useMemo(() => warehouse?.semantic_locations || [], [warehouse])
  const [source, setSource] = useState('')
  const [destination, setDestination] = useState('')
  const [priority, setPriority] = useState(3)

  const active = tasks.active || []
  const pending = tasks.pending || []
  const cancelled = tasks.cancelled || []
  const failed = tasks.failed || []
  const storage = (tasks.stored_count ?? 0) > 0 || active.concat(pending).some((task) => task.stage === 'putaway')
  const assigneeLabel = (id) => {
    const owner = robots.find((robot) => robot.id === id)
    return owner?.name || `R${id}`
  }

  return (
    <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-900">Task queue</h2>
        <p className="text-xs text-slate-600">{tasks.completed_count}/{tasks.total_count} put away</p>
      </div>

      <div className="rounded border border-slate-200 bg-slate-50 p-2 text-xs text-slate-700">
        <p className="font-semibold text-slate-900">Workflow</p>
        {storage ? (
          <>
            <p className="mt-1">RECEIVE → PUTAWAY → STORE</p>
            <p className="text-[11px] text-slate-500">Then the fleet docks and charges</p>
            <p className="mt-1 text-[11px] text-slate-500">{tasks.tables_loaded ?? 0} cartons still on tables · {tasks.in_racks ?? 0} in racks</p>
          </>
        ) : (
          <p className="mt-1">RECEIVE → PICK UP → TRANSPORT → DELIVER</p>
        )}
      </div>

      <form
        className="space-y-2 rounded border border-blue-200 bg-blue-50 p-2"
        onSubmit={(event) => {
          event.preventDefault()
          if (source && destination) sendCommand('create_task', { source, destination, priority: Number(priority) })
        }}
      >
        <p className="text-xs font-semibold text-slate-900">Insert semantic task</p>
        <div className="grid grid-cols-2 gap-2">
          <select aria-label="Task source" value={source} onChange={(event) => setSource(event.target.value)} className="min-w-0 rounded border border-slate-300 bg-white p-2 text-xs">
            <option value="">Source…</option>
            {locations.map((item) => <option key={`source-${item.id}`} value={item.id}>{item.label}</option>)}
          </select>
          <select aria-label="Task destination" value={destination} onChange={(event) => setDestination(event.target.value)} className="min-w-0 rounded border border-slate-300 bg-white p-2 text-xs">
            <option value="">Destination…</option>
            {locations.map((item) => <option key={`destination-${item.id}`} value={item.id}>{item.label}</option>)}
          </select>
        </div>
        <div className="flex gap-2">
          <select aria-label="Task priority" value={priority} onChange={(event) => setPriority(event.target.value)} className="rounded border border-slate-300 bg-white p-2 text-xs">
            {[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>Priority {value}</option>)}
          </select>
          <button type="submit" disabled={!source || !destination} className="min-h-9 flex-1 rounded bg-blue-600 px-3 text-xs font-semibold text-white disabled:opacity-50">Add to live queue</button>
        </div>
      </form>

      <div className="max-h-44 space-y-2 overflow-y-auto pr-1">
        {active.map((task) => <TaskRow key={`active-${task.id}`} task={task} state={assigneeLabel(task.assigned_to)} destinations={locations} />)}
        {pending.map((task) => <TaskRow key={`pending-${task.id}`} task={task} state="pending" destinations={locations} />)}
        {failed.map((task) => <TaskRow key={`failed-${task.id}`} task={task} state="failed" destinations={locations} />)}
        {cancelled.map((task) => <TaskRow key={`cancelled-${task.id}`} task={task} state="cancelled" destinations={locations} />)}
        {!active.length && !pending.length && <p className="py-4 text-center text-xs text-slate-500">No queued tasks.</p>}
      </div>
    </section>
  )
}
