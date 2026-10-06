import { useMemo } from 'react'
import * as THREE from 'three'

export default function PathTrail({ path, color }) {
  const points = useMemo(() => {
    if (!path || path.length < 2) return []
    return path.map(([x, y]) => new THREE.Vector3(x + 0.5, 0.05, y + 0.5))
  }, [path])

  const geometry = useMemo(() => {
    if (points.length < 2) return null
    return new THREE.BufferGeometry().setFromPoints(points)
  }, [points])

  if (!geometry) return null

  return (
    <group>
      <line geometry={geometry}>
        <lineBasicMaterial color={color} transparent opacity={0.75} linewidth={2} />
      </line>
      {/* Waypoint discs on floor: ensures planned path is vividly visible from the robot's eye perspective */}
      {points.slice(1).map((pt, idx) => (
        <mesh key={idx} position={[pt.x, 0.022, pt.z]} rotation={[-Math.PI / 2, 0, 0]}>
          <circleGeometry args={[0.16, 16]} />
          <meshBasicMaterial color={color} transparent opacity={0.5} depthWrite={false} />
        </mesh>
      ))}
    </group>
  )
}
