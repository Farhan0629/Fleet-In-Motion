import useStore from '../store'
import Controls from './Controls'
import RobotStatus from './RobotStatus'
import MetricsPanel from './MetricsPanel'
import TaskQueue from './TaskQueue'
import EventLog from './EventLog'
import { getMissionSummary, getRobotNextDestination } from '../utils/simulationState.js'

function SelectedInspector({ robot, offline }) {
  const destination = getRobotNextDestination(robot)

  return (
    <section className="space-y-2 rounded-lg border border-slate-200 bg-white p-3">
      <h2 className="text-sm font-semibold text-slate-900">Selected unit</h2>
      {robot ? (
        <>
          <p className="text-sm font-semibold text-slate-900">
            {robot.name || `UNIT-${String(robot.id).padStart(2, '0')}`}
            {offline && <span className="ml-2 rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-rose-700">Radio offline</span>}
          </p>
          <p className="text-xs text-slate-600">Status: {robot.status}</p>
          <p className="text-xs text-slate-600">
            Cargo: {robot.has_cargo ? `PKG-${String(robot.carrying_task_id || robot.task?.id || 0).padStart(3, '0')}` : 'None'}
            {robot.task?.table_code ? ` · from table ${robot.task.table_code}` : ''}
            {robot.task?.slot_code ? ` · to rack slot ${robot.task.slot_code}` : ''}
          </p>
          <p className="text-xs text-slate-600">
            Energy: {Math.round(robot.battery)}%{robot.battery_low ? ' · below threshold' : ''}
            {robot.charger_label ? ` · ${robot.parked ? 'parked on' : 'booked'} ${robot.charger_label}` : ''}
          </p>
          <p className="text-xs text-slate-600">
            Next stop: {destination ? `${destination.type} (${destination.coordinate[0]},${destination.coordinate[1]})` : 'Awaiting task'}
          </p>
        </>
      ) : (
        <p className="text-xs text-slate-600">Select a robot card to inspect and use follow camera.</p>
      )}
    </section>
  )
}

export default function Dashboard() {
  const robots = useStore((s) => s.robots)
  const sim = useStore((s) => s.sim)
  const tasks = useStore((s) => s.tasks)
  const network = useStore((s) => s.network)
  const selectedRobotId = useStore((s) => s.selectedRobotId)

  const selectedRobot = robots.find((robot) => robot.id === selectedRobotId)
  const mission = getMissionSummary(tasks)
  const partitioned = network?.partitioned ?? []
  const barrierBlocked = robots.filter((robot) => robot.navigation_blocked_reason === 'barrier')

  return (
    <div className="space-y-3 p-3 md:p-4">
      <section className="rounded-lg border border-slate-200 bg-white p-3">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Live mission summary</h2>
            <p className="text-xs text-slate-600">{sim.running ? (sim.paused ? 'Paused' : 'Running') : 'Stopped'} • {sim.speed}x</p>
          </div>
          <div className="text-right">
            <p className="text-xl font-semibold text-slate-900">{mission.progress}%</p>
            <p className="text-xs text-slate-500">complete</p>
          </div>
        </div>
        <div className="mt-2 grid grid-cols-4 gap-2 text-xs">
          <div className="rounded border border-slate-200 bg-slate-50 p-2 text-slate-700">Pending <span className="block text-sm font-semibold text-slate-900">{mission.pending}</span></div>
          <div className="rounded border border-slate-200 bg-slate-50 p-2 text-slate-700">Active <span className="block text-sm font-semibold text-slate-900">{mission.active}</span></div>
          <div className="rounded border border-slate-200 bg-slate-50 p-2 text-slate-700">On tables <span className="block text-sm font-semibold text-slate-900">{mission.tablesLoaded}</span></div>
          <div className="rounded border border-slate-200 bg-slate-50 p-2 text-slate-700">In racks <span className="block text-sm font-semibold text-slate-900">{mission.inRacks}</span></div>
        </div>
      </section>

      {barrierBlocked.length > 0 && (
        <section role="alert" className="sticky top-0 z-10 rounded-lg border border-rose-300 bg-rose-50 p-3 text-rose-800 shadow-sm">
          <h2 className="text-sm font-semibold">Please remove the barrier</h2>
          <p className="mt-1 text-xs">Barrier blockage for {barrierBlocked.map((robot) => robot.name || `Unit ${robot.id}`).join(', ')}. No usable exit or destination route. Pause and open a gap, then resume.</p>
        </section>
      )}

      <Controls />
      <SelectedInspector robot={selectedRobot} offline={selectedRobot ? partitioned.includes(selectedRobot.id) : false} />
      <MetricsPanel />

      <section className="space-y-2 rounded-lg border border-slate-200 bg-white p-3">
        <h2 className="text-sm font-semibold text-slate-900">Robot fleet</h2>
        <div className="space-y-2">
          {robots.map((robot) => <RobotStatus key={robot.id} robot={robot} />)}
          {!robots.length && <p className="text-xs text-slate-500">Waiting for robot state from backend.</p>}
        </div>
      </section>

      <TaskQueue />
      <EventLog />
    </div>
  )
}
