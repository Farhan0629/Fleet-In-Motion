// Pure presentation math: testable without React or WebGL.
export const RIG = Object.freeze({ hip: 0.83, chest: 1.15, shoulder: 1.34, head: 1.59, upperLeg: 0.34, lowerLeg: 0.36 })
export const CARRY = Object.freeze([0, 1.04, 0.35])
export const STATION = Object.freeze([0, 0.91, 0.40])
export const CARTON_SIZE = Object.freeze([0.36, 0.28, 0.30])
export const RACK_DECK_THICKNESS = 0.035
export const RACK_DECK_LEVELS = Object.freeze({
  lowRack: Object.freeze([0.24]),
  standard: Object.freeze([0.24, 1.0, 1.76]),
})
export const rackStoreLevel = (shelfView = 'lowRack') => (
  shelfView === 'lowRack' ? RACK_DECK_LEVELS.lowRack[0] : RACK_DECK_LEVELS.standard[1]
)
export const rackCartonCenterY = (shelfView = 'lowRack') => (
  rackStoreLevel(shelfView) + RACK_DECK_THICKNESS / 2 + CARTON_SIZE[1] / 2
)
export const rackSlotWorldPosition = (slot, shelfView = 'lowRack') => [
  slot.cell[0] + 0.5,
  rackCartonCenterY(shelfView),
  slot.cell[1] + 0.5,
]
// Rack transfers do not happen at table height: the lower deck sits near the
// floor and the upper deck at chest height, so the hands have to meet the shelf.
export const RACK_STATION_LOW = Object.freeze([0, rackCartonCenterY('lowRack'), 0.44])
export const RACK_STATION_HIGH = Object.freeze([0, rackCartonCenterY('standard'), 0.44])
export const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v))
export const smooth = (v) => { const t = clamp(v); return t * t * (3 - 2 * t) }
// Model faces +Z; backend heading 0 means +X.
export const headingToYaw = (degrees = 0) => Math.PI / 2 - degrees * Math.PI / 180
export const angleDelta = (from, to) => Math.atan2(Math.sin(to - from), Math.cos(to - from))
// Shared colour ramp for every battery readout: 3D pack LEDs, dashboard bar and badge.
export const batteryTone = (level = 0) => (level > 60 ? '#31a06a' : level > 30 ? '#d99a2b' : '#d1495b')
export function createMotion(x, z) { return { x, z, endX: x, endZ: z, queue: [] } }
export function queueMotion(m, x, z, duration = 0.2, snap = false) {
  const distance = Math.abs(x - m.endX) + Math.abs(z - m.endZ)
  if (snap || distance > 1.01 || m.queue.length > 4) {
    Object.assign(m, createMotion(x, z)); return
  }
  if (distance < 0.001) return
  m.queue.push({ x0: m.endX, z0: m.endZ, x, z, time: 0, duration: Math.max(0.025, duration) })
  m.endX = x; m.endZ = z
}
export function advanceMotion(m, delta, paused = false) {
  if (paused) return 0
  const oldX = m.x, oldZ = m.z
  let time = Math.min(Math.max(delta, 0), 0.1)
  while (m.queue.length && time > 0) {
    const segment = m.queue[0]
    const step = Math.min(time, segment.duration - segment.time)
    segment.time += step; time -= step
    const t = clamp(segment.time / segment.duration)
    m.x = segment.x0 + (segment.x - segment.x0) * t
    m.z = segment.z0 + (segment.z - segment.z0) * t
    if (t >= 1) m.queue.shift()
  }
  return Math.hypot(m.x - oldX, m.z - oldZ)
}
// `station` is where the package rests when it is not in the robot's hands: a
// loading/delivery table by default, or a rack deck during a storage transfer.
export function transferPose(handling, station = STATION) {
  if (!handling) return { position: [...CARRY], reach: 0, label: 'Transporting' }
  const p = clamp(handling.progress || 0)
  const lift = smooth((p - 0.25) / 0.5)
  const t = handling.kind === 'pickup' ? lift : 1 - lift
  const rack = handling.place === 'rack'
  return {
    position: station.map((value, i) => value + (CARRY[i] - value) * t),
    reach: 1 - t,
    label: handling.kind === 'pickup'
      ? (p < 0.25 ? (rack ? 'Reaching into rack' : 'Reaching') : p < 0.8 ? (rack ? 'Lifting off shelf' : 'Lifting package') : 'Securing package')
      : (p < 0.25 ? 'Aligning package' : p < 0.8 ? (rack ? 'Sliding onto shelf' : 'Placing package') : 'Releasing package'),
  }
}
export function chooseFollowRobot(robots, selectedId, previousId) {
  return robots.find((r) => r.id === selectedId) || robots.find((r) => r.id === previousId) || robots[0] || null
}
