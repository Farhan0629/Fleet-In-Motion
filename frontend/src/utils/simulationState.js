// Single source of truth for "where is every carton right now".
// A carton is drawn in exactly ONE place per frame: the table the backend still
// reports as loaded, the arms of the unit carrying it, the transfer animation
// during a lift/place dwell, or the rack slot that now holds it. Nothing is
// inferred from task lists, so a carton can never appear twice or out of thin
// air.
export const STATUS_COPY = {
  idle: { label: 'Idle', tone: 'slate' }, moving_to_pickup: { label: 'To table', tone: 'amber' }, picking_up: { label: 'Lifting carton', tone: 'amber' }, moving_to_dropoff: { label: 'Carrying to rack', tone: 'cobalt' }, placing: { label: 'Placing carton', tone: 'green' }, waiting: { label: 'Waiting', tone: 'amber' }, yielding: { label: 'Yielding', tone: 'amber' }, charging: { label: 'Charging', tone: 'green' }, moving_to_charge: { label: 'To charge pad', tone: 'green' }, storing: { label: 'Storing in rack', tone: 'violet' }, retrieving: { label: 'Picking from rack', tone: 'violet' }, parked: { label: 'Parked \u00b7 charged', tone: 'green' },
}
export function getRobotStatusMeta(robot) {
  if (robot?.navigation_message) return { label: robot.navigation_message, tone: 'rose' }
  if (robot?.handling) {
    if (robot.handling.place === 'rack') return STATUS_COPY[robot.handling.kind === 'pickup' ? 'retrieving' : 'storing']
    return STATUS_COPY[robot.handling.kind === 'pickup' ? 'picking_up' : 'placing']
  }
  if (['charging', 'moving_to_charge'].includes(robot?.status)) return STATUS_COPY[robot.status]
  if (robot?.parked) return STATUS_COPY.parked
  if (['waiting', 'yielding'].includes(robot?.status)) return STATUS_COPY[robot.status]
  if (robot?.has_cargo) return STATUS_COPY.moving_to_dropoff
  return STATUS_COPY[robot?.status] || { label: robot?.status || 'Unknown', tone: 'slate' }
}
export function getRobotNextDestination(robot) {
  if (robot?.charger && !robot?.task && !robot?.parked) return { type: 'CHARGING', coordinate: robot.charger }
  if (robot?.status === 'moving_to_charge' && robot.planned_path?.length) return { type: 'CHARGING', coordinate: robot.planned_path[robot.planned_path.length - 1] }
  if ((robot?.status === 'charging' || robot?.parked) && robot?.charger) return { type: robot.parked ? 'PARKED' : 'CHARGING', coordinate: robot.charger }
  if (!robot?.task) return null
  const coordinate = robot.has_cargo ? robot.task.dropoff : robot.task.pickup
  const kind = robot.has_cargo ? robot.task.dropoff_kind : robot.task.pickup_kind
  if (kind === 'rack') return { type: robot.task.slot_code ? `RACK ${robot.task.slot_code}` : 'RACK', coordinate }
  return { type: robot.task.table_code ? `TABLE ${robot.task.table_code}` : 'TABLE', coordinate }
}
// `warehouse` carries the physical truth: table state and slot state. Cartons
// mid-transfer are excluded from both, because the robot owns them while the
// dwell animation plays.
export function mapCargoLifecycle(tasks, robots, warehouse) {
  const fleet = robots || [], floor = warehouse || {}
  const transfers = new Set(fleet.filter((r) => r.handling).map((r) => r.handling.task_id))
  const tableCargo = (floor.tables || [])
    .filter((table) => table.state === 'loaded' && !transfers.has(table.task_id))
    .map((table) => ({ taskId: table.task_id, code: table.code, cell: table.cell, side: table.side }))
  const storedCargo = (floor.racks || [])
    .filter((slot) => slot.state === 'stored' && !transfers.has(slot.task_id))
    .map((slot) => ({ taskId: slot.task_id, code: slot.code, cell: slot.cell, access: slot.access }))
  const carryingCargo = fleet.filter((r) => r.has_cargo && r.task && !r.handling).map((r) => ({ taskId: r.task.id, robotId: r.id, dropoff: r.task.dropoff, slotCode: r.task.slot_code }))
  const handlingCargo = fleet.filter((r) => r.handling).map((r) => ({ ...r.handling, robotId: r.id }))
  return { tableCargo, storedCargo, carryingCargo, handlingCargo }
}
export function getMissionSummary(tasks) {
  const total = tasks?.total_count ?? 0, completed = tasks?.completed_count ?? 0
  return { total, completed, active: tasks?.active?.length ?? 0, pending: tasks?.pending?.length ?? 0, stored: tasks?.stored_count ?? 0, inRacks: tasks?.in_racks ?? 0, tablesLoaded: tasks?.tables_loaded ?? 0, progress: total > 0 ? Math.round(completed / total * 100) : 0 }
}
