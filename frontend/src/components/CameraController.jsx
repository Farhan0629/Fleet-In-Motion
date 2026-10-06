import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { Vector3 } from 'three'
import useStore from '../store'
import { chooseFollowRobot, headingToYaw } from '../utils/presentation.js'

function getPresets(warehouse) {
  const w = warehouse?.width ?? 20
  const h = warehouse?.height ?? 20
  const cx = w / 2
  const cz = h / 2
  const maxDim = Math.max(w, h)
  return {
    // High elevated architectural isometric view: looking downward at ~40 degrees
    // Entire facility in view, front wall and trucks sit comfortably in view without dominating foreground
    overview: [[cx + maxDim * 0.45, maxDim * 1.35, cz + maxDim * 1.25], [cx, 0.4, cz]],
    topdown: [[cx, maxDim * 1.7, cz + 0.01], [cx, 0.4, cz]],
  }
}

export default function CameraController() {
  const controls = useRef(), settled = useRef(false)
  const { camera } = useThree()
  const warehouse = useStore((s) => s.warehouse)
  const defaultTarget = useMemo(() => [
    (warehouse?.width ?? 20) / 2,
    0.4,
    (warehouse?.height ?? 20) / 2
  ], [warehouse?.width, warehouse?.height])
  const mode = useStore((s) => s.cameraMode)
  const revision = useStore((s) => s.cameraRevision)
  const reduced = useStore((s) => s.reducedMotion)
  const setMode = useStore((s) => s.setCameraMode)
  // While barriers are being painted, a drag has to mean "paint", not "orbit".
  // Zoom stays live so the floor can still be inspected mid-placement.
  const placeMode = useStore((s) => s.placeMode)
  const position = useMemo(() => new Vector3(), [])
  const target = useMemo(() => new Vector3(), [])

  useEffect(() => { settled.current = false }, [mode, revision])

  // Adjust camera Field-of-View: 65° for immersive first-person POV, 38° for architectural overview
  useEffect(() => {
    const targetFov = mode === 'pov' ? 65 : 38
    if (camera.fov !== targetFov) {
      camera.fov = targetFov
      camera.updateProjectionMatrix()
    }
  }, [mode, camera])

  useFrame((_, delta) => {
    if (!controls.current || mode === 'orbit') return
    const state = useStore.getState()
    if (mode === 'follow') {
      const robot = chooseFollowRobot(state.robots, state.selectedRobotId, state.followRobotId)
      if (!robot) return
      position.set(robot.x + 3.4, 3.0, robot.y + 4.2)
      target.set(robot.x + 0.5, 1.0, robot.y + 0.5)
    } else if (mode === 'pov') {
      const robot = chooseFollowRobot(state.robots, state.selectedRobotId, state.followRobotId)
      if (!robot) return
      // Compute heading in 3D world space (yaw angle)
      const desiredYaw = headingToYaw(robot.handling ? (robot.handling.face ?? 0) : robot.heading)
      const forwardX = Math.sin(desiredYaw)
      const forwardZ = Math.cos(desiredYaw)
      // Eye position: at robot eye level (1.56m), slightly forward from the torso axis (0.12m)
      const eyeX = robot.x + 0.5 + forwardX * 0.12
      const eyeY = 1.56
      const eyeZ = robot.y + 0.5 + forwardZ * 0.12
      position.set(eyeX, eyeY, eyeZ)

      // When actively handling (picking up or placing carton), tilt camera down towards the station/shelf
      // so the arms lifting or sliding the parcel are vividly visible in the center of the view!
      if (robot.handling) {
        const targetX = eyeX + forwardX * 1.05
        const targetY = robot.handling.place === 'rack' ? 0.75 : 0.88
        const targetZ = eyeZ + forwardZ * 1.05
        target.set(targetX, targetY, targetZ)
      } else {
        // When carrying / moving, tilt downward towards 1.10m so the carried box in hands is visible
        // in the lower third while the aisle path runway lights extend ahead
        target.set(eyeX + forwardX * 5.0, 1.10, eyeZ + forwardZ * 5.0)
      }
    } else if (mode === 'focus' && state.focusTarget) {
      target.set(...state.focusTarget)
      position.copy(target).add(new Vector3(3, 2.5, 4))
    } else {
      if (settled.current) return
      const presets = getPresets(state.warehouse)
      const preset = presets[mode] || presets.overview
      position.set(...preset[0]); target.set(...preset[1])
    }
    const alpha = reduced ? 1 : (mode === 'pov' ? 1 - Math.exp(-12 * Math.min(delta, 0.1)) : 1 - Math.exp(-7 * Math.min(delta, 0.1)))
    camera.position.lerp(position, alpha)
    controls.current.target.lerp(target, alpha)
    controls.current.update()
    if (mode !== 'follow' && mode !== 'pov' && camera.position.distanceTo(position) < 0.015 && controls.current.target.distanceTo(target) < 0.015) {
      settled.current = true
    }
  })

  return (
    <OrbitControls
      ref={controls}
      makeDefault
      target={defaultTarget}
      minDistance={mode === 'pov' ? 0.1 : 2.5}
      maxDistance={Math.max(52, (warehouse?.width ?? 20) * 2.6)}
      maxPolarAngle={Math.PI / 2.03}
      enableDamping={!reduced}
      dampingFactor={0.12}
      enableRotate={!placeMode && mode !== 'pov'}
      enablePan={!placeMode && mode !== 'pov'}
      enableZoom={!placeMode && mode !== 'pov'}
      onStart={() => setMode('orbit')}
    />
  )
}
