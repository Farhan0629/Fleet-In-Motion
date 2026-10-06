import { useMemo } from 'react'
import * as THREE from 'three'
import Sign from './Signage'

function physicalBounds(zone) {
  return zone.metadata?.navigation_footprint || zone.bounds
}

/**
 * 3D Freight delivery trucks parked at outbound dock bays.
 * Scaled and low-profile to support the scene realistically without dominating the foreground.
 */
export function FreightTruck({ position = [0, 0], color = '#ffffff', orientation = 'south' }) {
  const [x, z] = position
  const transform = {
    north: { position: [x + 0.5, 0, z - 1.8], rotation: [0, Math.PI, 0] },
    south: { position: [x + 0.5, 0, z + 1.8], rotation: [0, 0, 0] },
    east: { position: [x + 1.8, 0, z + 0.5], rotation: [0, Math.PI / 2, 0] },
    west: { position: [x - 1.8, 0, z + 0.5], rotation: [0, -Math.PI / 2, 0] },
  }[orientation] || { position: [x + 0.5, 0, z + 1.8], rotation: [0, 0, 0] }
  return (
    <group position={transform.position} rotation={transform.rotation}>
      {/* Container Trailer Box (docked outside) */}
      <mesh position={[0, 1.15, 0]} castShadow receiveShadow>
        <boxGeometry args={[1.35, 1.55, 2.75]} />
        <meshStandardMaterial color={color} roughness={0.5} metalness={0.15} />
      </mesh>
      {/* Trailer Roof Cap */}
      <mesh position={[0, 1.95, 0]}>
        <boxGeometry args={[1.38, 0.06, 2.78]} />
        <meshStandardMaterial color="#64748b" roughness={0.6} />
      </mesh>
      {/* Truck Cab */}
      <mesh position={[0, 0.95, 1.8]} castShadow>
        <boxGeometry args={[1.3, 1.35, 0.95]} />
        <meshStandardMaterial color={color === '#ffffff' ? '#334155' : color} roughness={0.35} metalness={0.3} />
      </mesh>
      {/* Windshield */}
      <mesh position={[0, 1.25, 2.3]}>
        <boxGeometry args={[1.15, 0.45, 0.04]} />
        <meshStandardMaterial color="#38bdf8" roughness={0.1} metalness={0.8} />
      </mesh>
      {/* Wheels */}
      {[-0.7, 0.7].map((wx) =>
        [-0.85, 0.25, 1.75].map((wz, wi) => (
          <mesh key={`${wx}-${wi}`} position={[wx, 0.28, wz]} rotation={[0, 0, Math.PI / 2]}>
            <cylinderGeometry args={[0.28, 0.28, 0.16, 16]} />
            <meshStandardMaterial color="#0f172a" roughness={0.8} />
          </mesh>
        ))
      )}
      {/* Rear Bumper & Hazard Reflector */}
      <mesh position={[0, 0.35, -1.4]}>
        <boxGeometry args={[1.25, 0.08, 0.06]} />
        <meshStandardMaterial color="#eab308" />
      </mesh>
    </group>
  )
}

/**
 * Industrial Roll-up Dock Door Frames with overhead gooseneck safety lamp.
 */
export function DockDoor({ position = [0, 0], orientation = 'south' }) {
  const [x, z] = position
  const isSouth = orientation === 'south'
  const isNorth = orientation === 'north'
  const offsetZ = isSouth ? 0.48 : -0.48
  return (
    <group position={[x + 0.5, 0, z + 0.5 + offsetZ]}>
      {/* Door Frame Surround */}
      <mesh position={[0, 1.45, 0]}>
        <boxGeometry args={[1.85, 2.7, 0.14]} />
        <meshStandardMaterial color="#64748b" roughness={0.6} metalness={0.3} />
      </mesh>
      {/* Ribbed Roll-Up Shutter Panels */}
      <mesh position={[0, 1.4, isSouth ? 0.03 : -0.03]}>
        <boxGeometry args={[1.6, 2.5, 0.05]} />
        <meshStandardMaterial color="#cbd5e1" roughness={0.7} metalness={0.2} />
      </mesh>
      {/* Overhead Industrial Safety Lamp */}
      <mesh position={[0, 2.9, isSouth ? 0.18 : -0.18]}>
        <boxGeometry args={[0.22, 0.08, 0.24]} />
        <meshStandardMaterial color="#334155" />
      </mesh>
      <mesh position={[0, 2.84, isSouth ? 0.2 : -0.2]}>
        <sphereGeometry args={[0.06, 8, 8]} />
        <meshBasicMaterial color="#fef08a" />
      </mesh>
      {/* Yellow Safety Bollards flanking each dock door */}
      {[-0.95, 0.95].map((bx) => (
        <mesh key={`db-${bx}`} position={[bx, 0.38, isSouth ? -0.2 : 0.2]}>
          <cylinderGeometry args={[0.06, 0.06, 0.76, 12]} />
          <meshStandardMaterial color="#eab308" roughness={0.3} />
        </mesh>
      ))}
    </group>
  )
}

/**
 * U-Shaped Automated Sortation Conveyor Table Loop with rollers and moving parcels.
 */
export function SortationLoop({ zone }) {
  const [minX, minY, maxX, maxY] = zone.bounds
  const cx = (minX + maxX) / 2 + 0.5
  const cz = (minY + maxY) / 2 + 0.5
  const width = maxX - minX + 1
  const depth = maxY - minY + 1

  return (
    <group position={[0, 0, 0]}>
      {/* U-Shape Conveyor Frame */}
      {/* Left arm */}
      <mesh position={[minX + 1.0, 0.76, cz]} castShadow receiveShadow>
        <boxGeometry args={[0.82, 0.14, depth - 0.2]} />
        <meshStandardMaterial color="#eab308" metalness={0.6} roughness={0.3} />
      </mesh>
      {/* Right arm */}
      <mesh position={[maxX, 0.76, cz]} castShadow receiveShadow>
        <boxGeometry args={[0.82, 0.14, depth - 0.2]} />
        <meshStandardMaterial color="#eab308" metalness={0.6} roughness={0.3} />
      </mesh>
      {/* Bottom connecting loop cross-table */}
      <mesh position={[cx, 0.76, maxY + 0.5]} castShadow receiveShadow>
        <boxGeometry args={[width - 0.2, 0.14, 0.82]} />
        <meshStandardMaterial color="#eab308" metalness={0.6} roughness={0.3} />
      </mesh>
      {/* Galvanized Conveyor Rollers (instanced look) */}
      {Array.from({ length: 14 }, (_, i) => (
        <mesh key={`r-bot-${i}`} position={[minX + 0.9 + i * 0.42, 0.84, maxY + 0.5]} rotation={[0, 0, Math.PI / 2]}>
          <cylinderGeometry args={[0.038, 0.038, 0.72, 12]} />
          <meshStandardMaterial color="#94a3b8" metalness={0.8} roughness={0.2} />
        </mesh>
      ))}
      {/* Conveyor Support Legs */}
      {[minX + 1.0, maxX].map((lx) =>
        [minY + 0.5, cz, maxY + 0.5].map((lz, li) => (
          <mesh key={`${lx}-${li}`} position={[lx, 0.38, lz]}>
            <boxGeometry args={[0.06, 0.76, 0.06]} />
            <meshStandardMaterial color="#334155" metalness={0.6} />
          </mesh>
        ))
      )}
      {/* Sample Parcels on Conveyor Belt */}
      {[
        [minX + 1.0, maxY + 0.5],
        [cx - 0.8, maxY + 0.5],
        [cx + 0.8, maxY + 0.5],
        [maxX, maxY + 0.5],
        [minX + 1.0, cz],
        [maxX, cz],
      ].map(([px, pz], pi) => (
        <mesh key={`box-${pi}`} position={[px, 0.96, pz]} castShadow>
          <boxGeometry args={[0.38, 0.26, 0.32]} />
          <meshStandardMaterial color={pi % 2 === 0 ? '#c29b68' : '#d97706'} roughness={0.7} />
        </mesh>
      ))}
      {/* Overhead Hanging Sign */}
      <Sign at={[cx, 2.7, cz]} title="SORTATION AREA" subtitle="Automated Induction Loop" tone="#0284c7" width={2.4} hang={0.7} />
    </group>
  )
}

/**
 * Restricted High-Voltage Power Substation with transformers, cabinets, and safety railing.
 */
export function RestrictedZone({ zone }) {
  const [minX, minY, maxX, maxY] = zone.bounds
  const cx = (minX + maxX) / 2 + 0.5
  const cz = (minY + maxY) / 2 + 0.5
  const width = maxX - minX + 1
  const depth = maxY - minY + 1

  return (
    <group position={[0, 0, 0]}>
      {/* Red Safety Floor Containment Pad */}
      <mesh position={[cx, 0.015, cz]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[width, depth]} />
        <meshBasicMaterial color="#b91c1c" transparent opacity={0.35} depthWrite={false} />
      </mesh>
      {/* Yellow/Black Perimeter Hazard Border */}
      <mesh position={[cx, 0.016, cz]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[Math.min(width, depth) * 0.44, Math.max(width, depth) * 0.52, 4]} />
        <meshBasicMaterial color="#eab308" transparent opacity={0.75} depthWrite={false} />
      </mesh>
      {/* Power Distribution Transformer Cabinets */}
      {[-1.6, -0.5, 0.6, 1.7].map((offset, i) => (
        <group key={i} position={[cx + offset, 0, cz]}>
          <mesh position={[0, 0.85, 0]} castShadow>
            <boxGeometry args={[0.78, 1.7, 0.82]} />
            <meshStandardMaterial color="#475569" roughness={0.5} metalness={0.5} />
          </mesh>
          <mesh position={[0, 1.72, 0]}>
            <boxGeometry args={[0.82, 0.06, 0.86]} />
            <meshStandardMaterial color="#1e293b" />
          </mesh>
          {/* Warning high-voltage plate */}
          <mesh position={[0, 1.15, 0.42]}>
            <planeGeometry args={[0.24, 0.24]} />
            <meshBasicMaterial color="#eab308" />
          </mesh>
        </group>
      ))}
      {/* Perimeter Safety Railings */}
      {[-width / 2 + 0.1, width / 2 - 0.1].map((rx) => (
        <mesh key={`post-${rx}`} position={[cx + rx, 0.5, cz]}>
          <boxGeometry args={[0.04, 1.0, depth]} />
          <meshStandardMaterial color="#ea580c" roughness={0.4} />
        </mesh>
      ))}
      {/* Overhead Hazard Sign */}
      <Sign at={[cx, 2.7, cz]} title="RESTRICTED ZONE" subtitle="High Voltage Substation · Authorized Only" tone="#b91c1c" width={2.8} hang={0.7} />
    </group>
  )
}

/**
 * Stacks of euro-pallets or QA inspection workbenches in auxiliary zones.
 */
export function AuxiliaryZone({ zone }) {
  const [minX, minY, maxX, maxY] = physicalBounds(zone)
  const cx = (minX + maxX) / 2 + 0.5
  const cz = (minY + maxY) / 2 + 0.5
  const width = maxX - minX + 1
  const depth = maxY - minY + 1
  const visualType = zone.metadata?.visual_type
  const isPallets = ['pallet_storage', 'dispatch_buffer', 'returns'].includes(visualType)
    || zone.id === 'empty_pallet_zone'
    || zone.id === 'staging_area'
  const isControlRoom = visualType === 'control_room'

  return (
    <group position={[cx, 0, cz]}>
      {isPallets ? (
        // Stack of realistic wooden pallets
        [0, 0.16, 0.32, 0.48, 0.64].map((py, idx) => (
          <group key={idx} position={[0, py, 0]}>
            <mesh position={[0, 0.08, 0]} castShadow receiveShadow>
              <boxGeometry args={[Math.max(0.7, width - 0.2), 0.03, Math.max(0.7, depth - 0.25)]} />
              <meshStandardMaterial color="#d4a373" roughness={0.8} />
            </mesh>
            {[-0.32, 0, 0.32].map((ratio) => (
              <mesh key={ratio} position={[ratio * width, 0.03, 0]}>
                <boxGeometry args={[0.1, 0.07, Math.max(0.65, depth - 0.3)]} />
                <meshStandardMaterial color="#b08968" roughness={0.9} />
              </mesh>
            ))}
          </group>
        ))
      ) : isControlRoom ? (
        <group>
          <mesh position={[0, 1.1, 0]} castShadow receiveShadow>
            <boxGeometry args={[Math.max(1.2, width - 0.35), 2.1, Math.max(1.2, depth - 0.35)]} />
            <meshStandardMaterial color="#e2e8f0" roughness={0.55} metalness={0.15} />
          </mesh>
          {[-0.9, 0, 0.9].map((offset) => <mesh key={offset} position={[offset, 1.15, Math.min(1.22, depth / 2)]}>
            <boxGeometry args={[0.62, 0.38, 0.05]} />
            <meshBasicMaterial color="#38bdf8" />
          </mesh>)}
        </group>
      ) : (
        // QA inspection / packing workbench
        <group>
          <mesh position={[0, 0.74, 0]} castShadow receiveShadow>
            <boxGeometry args={[Math.max(0.7, width - 0.3), 0.06, Math.max(0.7, depth - 0.3)]} />
            <meshStandardMaterial color="#e2e8f0" roughness={0.3} metalness={0.6} />
          </mesh>
          {[-1, 1].map((sideX) =>
            [-1, 1].map((sideZ) => (
              <mesh key={`${sideX}-${sideZ}`} position={[sideX * Math.max(0.25, width / 2 - 0.22), 0.36, sideZ * Math.max(0.25, depth / 2 - 0.22)]}>
                <boxGeometry args={[0.04, 0.72, 0.04]} />
                <meshStandardMaterial color="#64748b" metalness={0.7} />
              </mesh>
            ))
          )}
          {/* Inspection tool boxes */}
          <mesh position={[0, 0.88, -0.3]}>
            <boxGeometry args={[0.4, 0.22, 0.5]} />
            <meshStandardMaterial color="#94a3b8" />
          </mesh>
        </group>
      )}
      {/* Overhead Category Sign Badge */}
      <Sign at={[0, 2.5, 0]} title={zone.name} tone={zone.color} width={1.8} hang={0.6} />
    </group>
  )
}

function AutomatedStorageSystem({ zone }) {
  // `bounds` describes the semantic ASRS area and surrounding service aisle.
  // Solid geometry is constrained to the compiler-validated navigation
  // footprint so a valid AMR route can never visually pass through machinery.
  const [minX, minY, maxX, maxY] = zone.metadata?.navigation_footprint || zone.bounds
  const cx = (minX + maxX) / 2 + 0.5
  const cz = (minY + maxY) / 2 + 0.5
  const zoneWidth = maxX - minX + 1
  const zoneDepth = maxY - minY + 1
  const width = Math.max(2.8, zoneWidth - 0.35)
  const depth = Math.max(2.8, zoneDepth - 0.35)
  const height = 4.55
  const bays = 6
  const levels = 5
  const bayWidth = width / bays
  const frontZ = cz + depth / 2
  const backZ = cz - depth / 2
  const bayCenters = Array.from({ length: bays }, (_, index) => cx - width / 2 + bayWidth * (index + 0.5))
  const uprights = Array.from({ length: bays + 1 }, (_, index) => cx - width / 2 + bayWidth * index)
  const shelfLevels = Array.from({ length: levels }, (_, index) => 0.58 + index * 0.78)
  const parcelColors = ['#c9965f', '#d4a373', '#b7793f', '#e0b47a']

  const transferDeck = (side) => {
    const x = cx + side * (width * 0.27)
    const z = frontZ - 0.52
    return <group key={side}>
      <mesh position={[x, 0.67, z]} castShadow receiveShadow>
        <boxGeometry args={[1.2, 0.12, 0.72]} />
        <meshStandardMaterial color="#64748b" metalness={0.7} roughness={0.32} />
      </mesh>
      {Array.from({ length: 7 }, (_, index) => {
        const rollerX = x - 0.5 + index / 6
        return <mesh key={index} position={[rollerX, 0.76, z]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.035, 0.035, 0.62, 10]} />
          <meshStandardMaterial color="#cbd5e1" metalness={0.82} roughness={0.18} />
        </mesh>
      })}
      {[-0.48, 0.48].flatMap((xOffset) => [-0.27, 0.27].map((zOffset) => (
        <mesh key={`${xOffset}-${zOffset}`} position={[x + xOffset, 0.32, z + zOffset]}>
          <boxGeometry args={[0.07, 0.64, 0.07]} />
          <meshStandardMaterial color="#475569" metalness={0.62} roughness={0.38} />
        </mesh>
      )))}
      <mesh position={[x, 0.98, z]} castShadow>
        <boxGeometry args={[0.52, 0.34, 0.48]} />
        <meshStandardMaterial color="#c9965f" roughness={0.82} />
      </mesh>
    </group>
  }

  return <group>
    {/* Reinforced foundation and high-bay rack shell. */}
    <mesh position={[cx, 0.055, cz]} receiveShadow>
      <boxGeometry args={[width + 0.25, 0.11, depth + 0.25]} />
      <meshStandardMaterial color="#64748b" roughness={0.78} metalness={0.2} />
    </mesh>
    {[frontZ, backZ].map((faceZ, faceIndex) => <group key={faceZ}>
      {uprights.map((x) => <mesh key={x} position={[x, height / 2, faceZ]} castShadow>
        <boxGeometry args={[0.12, height, 0.14]} />
        <meshStandardMaterial color="#1e3a5f" metalness={0.68} roughness={0.34} />
      </mesh>)}
      {shelfLevels.map((level) => <mesh key={level} position={[cx, level, faceZ]}>
        <boxGeometry args={[width, 0.12, 0.16]} />
        <meshStandardMaterial color="#f59e0b" metalness={0.48} roughness={0.36} />
      </mesh>)}
      {bayCenters.flatMap((x, bay) => shelfLevels.map((level, row) => {
        const occupied = (bay + row + faceIndex) % 3 !== 1
        if (!occupied) return null
        return <mesh key={`${x}-${level}`} position={[x, level + 0.29, faceZ + (faceIndex === 0 ? -0.22 : 0.22)]} castShadow>
          <boxGeometry args={[bayWidth * 0.66, 0.48, 0.68]} />
          <meshStandardMaterial color={parcelColors[(bay + row) % parcelColors.length]} roughness={0.8} />
        </mesh>
      }))}
    </group>)}
    {/* Roof ties make the two storage faces read as one deep automated store. */}
    {uprights.map((x) => <mesh key={`roof-${x}`} position={[x, height, cz]}>
      <boxGeometry args={[0.12, 0.12, depth]} />
      <meshStandardMaterial color="#334155" metalness={0.7} roughness={0.3} />
    </mesh>)}
    {/* Twin yellow stacker-crane portals and visible lift carriages. */}
    {[-1, 1].map((side) => {
      const x = cx + side * (width / 2 - 0.16)
      return <group key={side}>
        {[frontZ, backZ].map((z) => <mesh key={z} position={[x, height / 2, z]} castShadow>
          <boxGeometry args={[0.2, height, 0.2]} />
          <meshStandardMaterial color="#eab308" metalness={0.58} roughness={0.32} />
        </mesh>)}
        <mesh position={[x, height, cz]} castShadow>
          <boxGeometry args={[0.24, 0.22, depth + 0.25]} />
          <meshStandardMaterial color="#facc15" metalness={0.55} roughness={0.3} />
        </mesh>
      </group>
    })}
    {/* Ground-supported transfer decks stay inside the blocked machine core. */}
    {[-1, 1].map(transferDeck)}
    {/* Yellow safety fence across the operator-facing edge. */}
    {Array.from({ length: 11 }, (_, index) => {
      const x = cx - (width + 1.0) / 2 + index * ((width + 1.0) / 10)
      return <mesh key={x} position={[x, 0.55, frontZ + 0.12]}>
        <boxGeometry args={[0.07, 1.1, 0.07]} />
        <meshStandardMaterial color="#eab308" roughness={0.35} />
      </mesh>
    })}
    {[0.34, 0.72, 1.04].map((level) => <mesh key={level} position={[cx, level, frontZ + 0.12]}>
      <boxGeometry args={[width + 1.05, 0.065, 0.065]} />
      <meshStandardMaterial color="#eab308" roughness={0.35} />
    </mesh>)}
    <Sign
      at={[cx, 5.35, frontZ + 0.18]}
      title={zone.name}
      subtitle="High-bay automated storage & retrieval"
      tone={zone.color || '#b91c1c'}
      width={4.4}
      maxWidth={5.2}
      hang={0.45}
    />
  </group>
}

/**
 * Storage Quadrant Signage & Corner Safety Bollards (RACK A, B, C, D).
 */
export function QuadrantSignAndBollards({ zone }) {
  const [minX, minY, maxX, maxY] = zone.bounds
  const cx = (minX + maxX) / 2 + 0.5
  const cz = (minY + maxY) / 2 + 0.5
  const isAsrs = zone.metadata?.automation === 'asrs'

  return (
    <group position={[0, 0, 0]}>
      {isAsrs && <AutomatedStorageSystem zone={zone} />}
      {/* Prominent High-Visibility Overhead Quadrant Sign Badge */}
      {!isAsrs && <Sign at={[cx, 3.1, cz]} title={zone.name} tone={zone.color || '#ea580c'} width={2.2} hang={0.65} />}
    </group>
  )
}

/**
 * Painted Roadway Floor Markings: Zebra Crosswalks & Hazard Borders.
 */
/**
 * Painted Roadway Floor Markings: Zebra Crosswalks, Dashed Robot Traffic Lanes, Directional Arrows, and Hazard Borders.
 */
export function RoadwayMarkings({ markings = [] }) {
  return (
    <group>
      {markings.map((m, idx) => {
        if (m.type === 'crosswalk') {
          const [x1, y1] = m.start
          const [x2, y2] = m.end
          const cx = (x1 + x2) / 2 + 0.5
          const cz = (y1 + y2) / 2 + 0.5
          const span = Math.max(Math.abs(x2 - x1), Math.abs(y2 - y1)) + 1
          const count = Math.max(5, Math.round(span * 3.5))
          return (
            <group key={`cw-${idx}`} position={[cx, 0.015, cz]}>
              {Array.from({ length: count }, (_, i) => (
                <mesh key={i} position={[(i - (count - 1) / 2) * 0.38, 0, 0]} rotation={[-Math.PI / 2, 0, 0]}>
                  <planeGeometry args={[0.22, 1.2]} />
                  <meshBasicMaterial color="#ffffff" transparent opacity={0.85} depthWrite={false} />
                </mesh>
              ))}
            </group>
          )
        }
        if (m.type === 'lane_divider') {
          const [x1, y1] = m.start
          const [x2, y2] = m.end
          const isH = y1 === y2
          const startCoord = isH ? Math.min(x1, x2) : Math.min(y1, y2)
          const endCoord = isH ? Math.max(x1, x2) : Math.max(y1, y2)
          const dashes = []
          for (let c = startCoord; c <= endCoord; c += 1.2) {
            dashes.push(c)
          }
          return (
            <group key={`ld-${idx}`}>
              {dashes.map((c, di) => (
                <mesh
                  key={di}
                  position={[isH ? c + 0.5 : x1 + 0.5, 0.014, isH ? y1 + 0.5 : c + 0.5]}
                  rotation={[-Math.PI / 2, 0, isH ? 0 : Math.PI / 2]}
                >
                  <planeGeometry args={[0.65, 0.08]} />
                  <meshBasicMaterial color="#ffffff" transparent opacity={0.8} depthWrite={false} />
                </mesh>
              ))}
            </group>
          )
        }
        if (m.type === 'arrow') {
          const [x, y] = m.start
          const dir = m.direction || 'east'
          const rotZ = dir === 'east' ? 0 : dir === 'west' ? Math.PI : dir === 'north' ? Math.PI / 2 : -Math.PI / 2
          return (
            <group key={`ar-${idx}`} position={[x + 0.5, 0.016, y + 0.5]} rotation={[-Math.PI / 2, 0, rotZ]}>
              {/* Arrow shaft */}
              <mesh position={[-0.15, 0, 0]}>
                <planeGeometry args={[0.45, 0.12]} />
                <meshBasicMaterial color="#facc15" transparent opacity={0.9} depthWrite={false} />
              </mesh>
              {/* Arrow head */}
              <mesh position={[0.18, 0, 0]} rotation={[0, 0, -Math.PI / 2]}>
                <circleGeometry args={[0.22, 3]} />
                <meshBasicMaterial color="#facc15" transparent opacity={0.9} depthWrite={false} />
              </mesh>
            </group>
          )
        }
        if (m.type === 'hazard_border') {
          const [x1, y1] = m.start
          const [x2, y2] = m.end
          const cx = (x1 + x2) / 2 + 0.5
          const cz = (y1 + y2) / 2 + 0.5
          const w = Math.abs(x2 - x1) + 1
          const d = Math.abs(y2 - y1) + 1
          return (
            <mesh key={`hb-${idx}`} position={[cx, 0.012, cz]} rotation={[-Math.PI / 2, 0, 0]}>
              <planeGeometry args={[w + 0.35, d + 0.35]} />
              <meshBasicMaterial color="#eab308" transparent opacity={0.25} depthWrite={false} />
            </mesh>
          )
        }
        return null
      })}
    </group>
  )
}
