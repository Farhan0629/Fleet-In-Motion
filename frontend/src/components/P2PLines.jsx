import { useMemo } from 'react'
import * as THREE from 'three'
import useStore from '../store'

/*
 * Animated lines between robots showing P2P communication.
 * Visually confirms decentralized mesh messaging.
 */
export default function P2PLines() {
  const robots = useStore((s) => s.robots)
  const p2pMessages = useStore((s) => s.p2pMessages)
  
  const connections = useMemo(() => {
    const conns = []
    const seen = new Set()
    
    for (const msg of p2pMessages) {
      const from = robots.find((r) => r.id === msg.from)
      if (!from) continue
      
      if (msg.to === 'all') {
        for (const to of robots) {
          if (to.id === msg.from) continue
          const key = `${Math.min(msg.from, to.id)}-${Math.max(msg.from, to.id)}`
          if (!seen.has(key)) {
            seen.add(key)
            conns.push({
              from: [from.x + 0.5, 0.6, from.y + 0.5],
              to: [to.x + 0.5, 0.6, to.y + 0.5],
            })
          }
        }
      } else {
        const to = robots.find((r) => r.id === msg.to)
        if (to) {
          const key = `${Math.min(msg.from, to.id)}-${Math.max(msg.from, to.id)}`
          if (!seen.has(key)) {
            seen.add(key)
            conns.push({
              from: [from.x + 0.5, 0.6, from.y + 0.5],
              to: [to.x + 0.5, 0.6, to.y + 0.5],
            })
          }
        }
      }
    }
    return conns
  }, [p2pMessages, robots])
  
  return (
    <group>
      {connections.map((conn, i) => {
        const p1 = new THREE.Vector3(...conn.from)
        const p2 = new THREE.Vector3(...conn.to)
        const geo = new THREE.BufferGeometry().setFromPoints([p1, p2])
        const mid = p1.clone().lerp(p2, 0.5)
        return (
          <group key={i}>
            <line geometry={geo}>
              <lineBasicMaterial color="#38bdf8" transparent opacity={0.8} linewidth={2} />
            </line>
            {/* Glowing mesh signal packet visible from robot eye perspective */}
            <mesh position={[mid.x, mid.y, mid.z]}>
              <sphereGeometry args={[0.075, 10, 8]} />
              <meshBasicMaterial color="#7dd3fc" transparent opacity={0.9} />
            </mesh>
          </group>
        )
      })}
    </group>
  )
}
