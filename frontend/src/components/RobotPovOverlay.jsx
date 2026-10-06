import useStore from '../store'
import { chooseFollowRobot } from '../utils/presentation.js'

export default function RobotPovOverlay() {
  const robots = useStore((s) => s.robots)
  const selectedRobotId = useStore((s) => s.selectedRobotId)
  const followRobotId = useStore((s) => s.followRobotId)
  const cameraMode = useStore((s) => s.cameraMode)
  const network = useStore((s) => s.network)

  if (cameraMode !== 'pov') return null

  const robot = chooseFollowRobot(robots, selectedRobotId, followRobotId)
  if (!robot) return null

  const name = robot.name || `UNIT-${String(robot.id).padStart(2, '0')}`
  const offline = (network?.partitioned ?? []).includes(robot.id)
  const battery = Math.round(robot.battery ?? 100)
  const heading = robot.heading ?? 0
  const cargoLabel = robot.has_cargo
    ? `PKG-${String(robot.carrying_task_id || robot.task?.id || 0).padStart(3, '0')}`
    : robot.handling
      ? `PKG-${String(robot.handling.task_id || 0).padStart(3, '0')}`
      : 'NONE'

  const statusLabel = robot.handling
    ? (robot.handling.kind === 'pickup' ? 'LIFTING PARCEL' : 'SLIDING ONTO SHELF')
    : robot.status.replace(/_/g, ' ').toUpperCase()

  return (
    <div
      className="pointer-events-none absolute inset-0 z-20 flex flex-col justify-between p-4 font-mono text-cyan-400 select-none"
      style={{
        boxShadow: 'inset 0 0 100px rgba(6, 182, 212, 0.22)',
        background: 'radial-gradient(ellipse at center, rgba(14, 165, 233, 0.04) 0%, rgba(2, 132, 199, 0.12) 100%)',
      }}
    >
      {/* Scanline pattern overlay */}
      <div
        className="pointer-events-none absolute inset-0 opacity-15"
        style={{
          backgroundImage: 'linear-gradient(rgba(56, 189, 248, 0.3) 1px, transparent 1px)',
          backgroundSize: '100% 4px',
        }}
      />

      {/* Corner brackets */}
      <div className="absolute top-3 left-3 h-6 w-6 border-t-2 border-l-2 border-cyan-400 opacity-80" />
      <div className="absolute top-3 right-3 h-6 w-6 border-t-2 border-r-2 border-cyan-400 opacity-80" />
      <div className="absolute bottom-3 left-3 h-6 w-6 border-b-2 border-l-2 border-cyan-400 opacity-80" />
      <div className="absolute bottom-3 right-3 h-6 w-6 border-b-2 border-r-2 border-cyan-400 opacity-80" />

      {/* Top telemetry banner */}
      <div className="relative flex items-start justify-between text-xs tracking-wider">
        <div className="space-y-1 bg-slate-950/75 p-2 rounded border border-cyan-500/40 backdrop-blur-sm">
          <div className="flex items-center gap-2 font-bold text-cyan-300">
            <span className="inline-block h-2 w-2 rounded-full bg-cyan-400 animate-pulse" />
            OPTICAL SENSOR FEED: ONBOARD CAM-01
          </div>
          <div className="text-[11px] text-cyan-200">
            OPERATOR: <span className="font-bold text-white">{name}</span>
            {offline && <span className="ml-2 text-rose-400 font-bold">[RADIO OFFLINE]</span>}
          </div>
          <div className="text-[11px] text-cyan-400">
            STATE: <span className="text-amber-300 font-semibold">{statusLabel}</span>
          </div>
        </div>

        <div className="text-right space-y-1 bg-slate-950/75 p-2 rounded border border-cyan-500/40 backdrop-blur-sm">
          <div className="text-[11px] text-cyan-300">
            CARGO: <span className="font-bold text-white">{cargoLabel}</span>
          </div>
          <div className="text-[11px]">
            BATTERY: <span className={battery < 50 ? 'text-amber-400 font-bold' : 'text-emerald-400 font-bold'}>{battery}% ⚡</span>
          </div>
          <div className="text-[10px] text-cyan-400/80">
            LiDAR BUMPER: <span className="text-emerald-400">5.0m ACTIVE</span>
          </div>
        </div>
      </div>

      {/* Center robotic targeting reticle / crosshair */}
      <div className="relative flex flex-col items-center justify-center opacity-85">
        <div className="relative flex items-center justify-center">
          {/* Outer compass ring */}
          <div className="h-28 w-28 rounded-full border border-dashed border-cyan-400/40 flex items-center justify-center animate-spin-slow">
            <div className="h-14 w-14 rounded-full border border-cyan-400/60" />
          </div>
          {/* Crosshairs */}
          <div className="absolute h-0.5 w-36 bg-cyan-400/40" />
          <div className="absolute h-36 w-0.5 bg-cyan-400/40" />
          {/* Center target dot */}
          <div className="absolute h-2 w-2 rounded-full bg-cyan-300 shadow-sm shadow-cyan-300" />
        </div>
        {/* Dynamic target lock text */}
        <div className="mt-2 text-[10px] tracking-widest text-cyan-300 bg-slate-950/60 px-2 py-0.5 rounded border border-cyan-500/30">
          HEADING: {heading}° • ELEVATION: 1.58M
        </div>
      </div>

      {/* Bottom telemetry status bar */}
      <div className="relative flex items-end justify-between text-xs tracking-wider">
        <div className="bg-slate-950/75 p-2 rounded border border-cyan-500/40 backdrop-blur-sm">
          <div className="text-[11px] text-cyan-300">
            FLOOR POS: <span className="font-bold text-white">({robot.x}, {robot.y})</span>
          </div>
          <div className="text-[10px] text-cyan-400/80">
            SPEED: 1.0 M/S • PATH LOCK: ENGAGED
          </div>
        </div>

        <div className="text-right bg-slate-950/75 p-2 rounded border border-cyan-500/40 backdrop-blur-sm">
          <div className="text-[10px] text-cyan-300">
            P2P MESH: <span className={offline ? 'text-rose-400' : 'text-emerald-400'}>{offline ? 'DISCONNECTED' : '10Hz SYNC'}</span>
          </div>
          <div className="text-[10px] text-cyan-400/80">
            FOV: 70° • SENSOR: INFRARED/OPTICAL
          </div>
        </div>
      </div>
    </div>
  )
}
