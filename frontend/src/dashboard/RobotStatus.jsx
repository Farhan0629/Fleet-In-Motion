import useStore from '../store'
import { getRobotNextDestination, getRobotStatusMeta } from '../utils/simulationState.js'
import { batteryTone } from '../utils/presentation.js'

const ACCENTS = ['#315c9f', '#6a86b8', '#3f6aaf', '#506fa8', '#7a8fb9']

export default function RobotStatus({ robot }) {
  const selectedRobotId = useStore((s) => s.selectedRobotId)
  const selectRobot = useStore((s) => s.selectRobot)
  const setFollowRobot = useStore((s) => s.setFollowRobot)
  const network = useStore((s) => s.network)

  const selected = selectedRobotId === robot.id
  const accent = ACCENTS[(robot.id - 1) % ACCENTS.length]
  const status = getRobotStatusMeta(robot)
  const destination = getRobotNextDestination(robot)
  const label = robot.name || `UNIT-${String(robot.id).padStart(2, '0')}`
  const offline = (network?.partitioned ?? []).includes(robot.id)
  const battery = Math.max(0, Math.min(100, robot.battery || 0))
  const charging = robot.status === 'charging'
  const heading = robot.status === 'moving_to_charge'
  const parked = Boolean(robot.parked)
  const pad = robot.charger_label

  return (
    <article
      className={`rounded-lg border bg-white p-3 shadow-sm transition ${selected ? 'border-blue-400 ring-2 ring-blue-100' : 'border-slate-200'}`}
      aria-label={`Robot ${label}`}
    >
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          onClick={() => selectRobot(robot.id)}
          className="min-h-11 min-w-11 text-left"
        >
          <p className="flex items-center gap-2 text-sm font-semibold" style={{ color: accent }}>
            {label}
            {offline && (
              <span className="rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-rose-700">
                Radio offline
              </span>
            )}
            {(charging || heading || parked) && (
              <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-emerald-700">
                {charging
                  ? `Charging${pad ? ` · ${pad}` : ''}`
                  : parked
                    ? `Parked${pad ? ` · ${pad}` : ''}`
                    : `Booked${pad ? ` ${pad}` : ' a pad'}`}
              </span>
            )}
          </p>
          <p className="text-xs text-slate-500">{status.label}</p>
        </button>
        <button
          type="button"
          onClick={() => setFollowRobot(robot.id)}
          className="min-h-11 rounded-md border border-slate-300 px-3 text-xs font-medium text-slate-700"
        >
          Follow
        </button>
      </div>

      {robot.navigation_message && (
        <p role="alert" className="mt-2 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700">
          {robot.navigation_message}
        </p>
      )}

      <div className="mt-2 h-2 rounded-full bg-slate-200">
        <div
          className={`h-2 rounded-full transition-all ${charging ? 'animate-pulse' : ''}`}
          style={{ width: `${Math.max(4, battery)}%`, backgroundColor: batteryTone(battery) }}
        />
      </div>

      <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-600">
        <p>Battery <span className="font-semibold" style={{ color: batteryTone(battery) }}>{Math.round(robot.battery)}%</span></p>
        <p>Put away <span className="font-semibold text-slate-900">{robot.tasks_completed}</span></p>
        <p>Location <span className="font-semibold text-slate-900">({robot.x},{robot.y})</span></p>
        <p>Charge runs <span className="font-semibold text-slate-900">{robot.charge_cycles ?? 0}</span></p>
        <p className="col-span-2">{robot.has_cargo ? `Carrying PKG-${String(robot.carrying_task_id || robot.task?.id || 0).padStart(3, '0')}${robot.task?.table_code ? ` · from ${robot.task.table_code}` : ''}${robot.task?.slot_code ? ` → slot ${robot.task.slot_code}` : ''}` : 'Empty handed'}</p>
      </div>

      <p className="mt-2 text-xs text-slate-600">
        Next destination:{' '}
        <span className="font-semibold text-slate-900">
          {destination ? `${destination.type} (${destination.coordinate[0]},${destination.coordinate[1]})` : 'Awaiting task'}
        </span>
      </p>
    </article>
  )
}
