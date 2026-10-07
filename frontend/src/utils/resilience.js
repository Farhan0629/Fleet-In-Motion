export function resilienceControls(robot, mission, sim, connected, offline) {
  const active = Boolean(connected && sim?.running && mission?.started && !['completed', 'failed', 'partial'].includes(mission.status))
  return {
    canFail: Boolean(active && robot?.available && !robot?.failed && robot?.task && !robot.task.recovery_required && !robot?.handling),
    canRestoreRobot: Boolean(connected && robot?.failed && !robot?.has_cargo && !robot?.task && !robot?.handling),
    canLoseCommunication: Boolean(active && robot && !offline && !robot.failed),
    canRestoreCommunication: Boolean(connected && robot && offline),
  }
}
