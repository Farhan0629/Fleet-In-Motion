import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Object3D } from 'three'
import { useFrame } from '@react-three/fiber'
import useStore from '../store'
import CargoBox from './CargoBox'
import BlockedAisle from './BlockedAisle'
import Sign from './Signage'
import {
  FreightTruck,
  DockDoor,
  SortationLoop,
  RestrictedZone,
  AuxiliaryZone,
  QuadrantSignAndBollards,
  RoadwayMarkings,
} from './SmartWarehouseElements'
import { sendCommand } from '../websocket'
import { mapCargoLifecycle } from '../utils/simulationState.js'
import {
  RACK_DECK_LEVELS,
  RACK_DECK_THICKNESS,
  rackSlotWorldPosition,
  stationFixtureLayout,
} from '../utils/presentation.js'
function Batch({ items, color, opacity = 1 }) {
  const ref = useRef()
  useLayoutEffect(() => {
    if (!ref.current) return
    const dummy = new Object3D()
    items.forEach(({ at, size }, index) => { dummy.position.set(...at); dummy.scale.set(...size); dummy.updateMatrix(); ref.current.setMatrixAt(index, dummy.matrix) })
    ref.current.instanceMatrix.needsUpdate = true
    ref.current.computeBoundingSphere()
  }, [items])
  if (!items.length) return null
  return <instancedMesh key={items.length} ref={ref} args={[null, null, items.length]} castShadow={opacity === 1} receiveShadow><boxGeometry args={[1, 1, 1]} /><meshStandardMaterial color={color} roughness={0.7} metalness={0.15} transparent={opacity < 1} opacity={opacity} depthWrite={opacity === 1} /></instancedMesh>
}
// Twelve staging tables, addressed T01..T12: six on the west aisle, six on the
// east. Every one of them starts the round with exactly ONE carton on it.
// The carton leaves the table the instant the lift dwell begins - from then on
// the robot owns it - and the table is never restocked during the round, so a
// carton can never appear on a table it has already left.
function Station({ table, staged, handling }) {
  const [x, z] = table.cell
  const side = table.side || 'west'
  const fixture = stationFixtureLayout(side)
  const [fixtureX, fixtureZ] = fixture.offset
  const tone = side === 'north' ? '#1d4ed8' : side === 'south' ? '#1e3a8a' : side === 'west' ? '#a56b1e' : '#2f6a8f'
  const busy = handling.some((h) => h.place !== 'rack' && h.station[0] === x && h.station[1] === z)
  const item = staged || null
  const state = busy
    ? 'Robot lifting carton'
    : item
      ? `Carton #${item.taskId} staged`
      : 'Cleared \u00b7 carton in racks'
  return <group position={[x + 0.5, 0, z + 0.5]}>
    <mesh position={[0, 0.012, 0]} rotation={[-Math.PI / 2, 0, 0]}><planeGeometry args={[0.96, 0.96]} /><meshBasicMaterial color={tone} transparent opacity={0.16} depthWrite={false} /></mesh>
    <mesh position={[fixtureX, 0.745, fixtureZ]} receiveShadow><boxGeometry args={fixture.topSize} /><meshStandardMaterial color="#61758a" metalness={0.5} roughness={0.4} /></mesh>
    {fixture.legOffsets.map(([lx, lz]) => <mesh key={`${lx}-${lz}`} position={[lx, 0.36, lz]}><boxGeometry args={[0.035, 0.72, 0.035]} /><meshStandardMaterial color="#8d9da9" /></mesh>)}
    {!busy && !item && <mesh position={[fixtureX, 0.776, fixtureZ]} rotation={[-Math.PI / 2, 0, 0]}><planeGeometry args={[fixture.topSize[0] * 0.72, fixture.topSize[2] * 0.72]} /><meshBasicMaterial color={tone} transparent opacity={0.34} depthWrite={false} /></mesh>}
    {!busy && item && <CargoBox taskId={item.taskId} position={[fixtureX, 0.91, fixtureZ]} rotation={[0, fixture.cargoRotation, 0]} />}
    <Sign at={[fixtureX, 2.14, fixtureZ]} title={`TABLE ${table.code}`} subtitle={state} tone={tone} width={1.7} hang={0.55} />
  </group>
}
// A charge pad is live infrastructure now: the ring breathes while a unit is
// docked, an energy bolt climbs the post, and the sign names the occupant so a
// judge can see the mesh booking held (only the name changes, so the sign
// texture is not rebuilt every tick).
function ChargerPad({ cell, index, occupant, claimant }) {
  const ring = useRef(), bolt = useRef()
  const [x, z] = cell
  const busy = Boolean(occupant)
  const post = z < 10 ? -0.42 : 0.42
  useFrame((state) => {
    const time = state.clock.elapsedTime
    if (ring.current) {
      const scale = busy ? 1 + 0.09 * Math.sin(time * 5) : 1
      ring.current.scale.set(scale, scale, scale)
      ring.current.material.opacity = busy ? 0.55 + 0.45 * (0.5 + 0.5 * Math.sin(time * 5)) : 0.75
    }
    if (bolt.current) {
      bolt.current.visible = busy
      if (busy) {
        const rise = (time * 0.7) % 1
        bolt.current.position.y = 0.12 + rise * 0.62
        bolt.current.material.opacity = 1 - rise
      }
    }
  })
  return <group position={[x + 0.5, 0, z + 0.5]}>
    <mesh ref={ring} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.015, 0]}><ringGeometry args={[0.29, 0.41, 32]} /><meshBasicMaterial color={busy ? '#4fb98a' : '#338969'} transparent opacity={0.75} depthWrite={false} /></mesh>
    <mesh position={[0, 0.26, post]}><boxGeometry args={[0.035, 0.52, 0.035]} /><meshStandardMaterial color="#7c8b9a" metalness={0.4} roughness={0.5} /></mesh>
    <mesh position={[0, 0.55, post]}><boxGeometry args={[0.11, 0.09, 0.055]} /><meshStandardMaterial color={busy ? '#297359' : '#61758a'} metalness={0.5} roughness={0.4} /></mesh>
    <mesh ref={bolt} position={[0, 0.12, post]} visible={false}><boxGeometry args={[0.06, 0.1, 0.06]} /><meshBasicMaterial color="#7bf1a8" transparent opacity={0.9} depthWrite={false} /></mesh>
    <Sign at={[0, 0.86, post]} title={`CHARGE ${index + 1}`} subtitle={occupant || claimant || undefined} tone={busy ? '#297359' : '#4a6072'} width={0.95} />
  </group>
}
// Hand placement of blockages. Only mounted while the demo is paused (or not
// started yet), so a judge can never drop an obstacle under a moving unit.
// Press on a free aisle cell and drag to paint a barrier; press on an existing
// barrier and drag to erase. The server re-validates every cell.
function BlockPlacement({ width, height }) {
  const [hover, setHover] = useState(null)
  const drag = useRef(null)
  useEffect(() => {
    const release = () => { drag.current = null }
    window.addEventListener('pointerup', release)
    window.addEventListener('pointercancel', release)
    return () => { window.removeEventListener('pointerup', release); window.removeEventListener('pointercancel', release) }
  }, [])
  const cellState = (x, y) => {
    const { warehouse, robots } = useStore.getState()
    if (!warehouse?.grid) return 'invalid'
    if (x < 0 || y < 0 || x >= warehouse.width || y >= warehouse.height) return 'invalid'
    if (warehouse.grid[y][x] !== 0) return 'invalid'
    if ((warehouse.blocked || []).some(([bx, by]) => bx === x && by === y)) return 'blocked'
    if (robots.some((robot) => robot.x === x && robot.y === y)) return 'invalid'
    return 'free'
  }
  const apply = (x, y) => {
    const mode = drag.current?.mode
    const state = cellState(x, y)
    if (mode === 'place' && state === 'free') sendCommand('block_aisle', { x, y })
    if (mode === 'erase' && state === 'blocked') sendCommand('unblock_aisle', { x, y })
  }
  const at = (event) => [Math.floor(event.point.x), Math.floor(event.point.z)]
  const remember = (x, y) => {
    const key = `${x}:${y}`
    if (drag.current.seen.has(key)) return false
    drag.current.seen.add(key)
    return true
  }
  return <group>
    <mesh
      position={[width / 2, 0.02, height / 2]}
      rotation={[-Math.PI / 2, 0, 0]}
      onPointerDown={(event) => {
        event.stopPropagation()
        const [x, y] = at(event)
        drag.current = { mode: cellState(x, y) === 'blocked' ? 'erase' : 'place', seen: new Set() }
        remember(x, y)
        apply(x, y)
        setHover([x, y, cellState(x, y)])
      }}
      onPointerMove={(event) => {
        const [x, y] = at(event)
        setHover((previous) => (previous && previous[0] === x && previous[1] === y ? previous : [x, y, cellState(x, y)]))
        if (!drag.current) return
        if (remember(x, y)) apply(x, y)
      }}
      onPointerUp={() => { drag.current = null }}
      onPointerOut={() => { setHover(null) }}
    >
      <planeGeometry args={[width, height]} />
      <meshBasicMaterial color="#2864b7" transparent opacity={0.05} depthWrite={false} />
    </mesh>
    {hover && <mesh position={[hover[0] + 0.5, 0.028, hover[1] + 0.5]} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[0.94, 0.94]} />
      <meshBasicMaterial color={hover[2] === 'free' ? '#dc2626' : hover[2] === 'blocked' ? '#facc15' : '#94a3b8'} transparent opacity={0.5} depthWrite={false} />
    </mesh>}
  </group>
}
export default function Warehouse() {
  const warehouse = useStore((s) => s.warehouse)
  const tasks = useStore((s) => s.tasks)
  const robots = useStore((s) => s.robots)
  const shelfView = useStore((s) => s.shelfView)
  const placeMode = useStore((s) => s.placeMode)
  const sim = useStore((s) => s.sim)
  const low = shelfView === 'lowRack'
  const liveSlots = useMemo(() => (warehouse?.racks || []).filter((slot) => slot.state !== 'empty'), [warehouse])
  const batches = useMemo(() => {
    const result = { posts: [], rails: [], decks: [], boxes: [], tape: [], walls: [], lanes: [] }
    if (!warehouse?.grid) return result
    const { grid, width, height } = warehouse
    const add = (list, at, size) => result[list].push({ at, size })
    // Build rack geometry from the same addressable shelf cells used by the
    // backend. Warehouse #2 contains 2x3 and irregular rack footprints, so a
    // visual-only 2x2 assumption left valid lower-row slots without a deck.
    const deckLevels = low ? RACK_DECK_LEVELS.lowRack : RACK_DECK_LEVELS.standard
    const decorLevel = low ? null : deckLevels.at(-1)
    const postKeys = new Set()
    const addPost = (x, z, h) => {
      const key = `${x}:${z}`
      if (postKeys.has(key)) return
      postKeys.add(key)
      add('posts', [x, h / 2, z], [0.075, h, 0.075])
    }
    for (let z = 0; z < height; z++) for (let x = 0; x < width; x++) {
      const cell = grid[z][x]
      if (cell === 1) {
        const cx = x + 0.5, cz = z + 0.5, h = low ? 0.76 : 2.15
        for (const px of [x + 0.06, x + 0.94]) for (const pz of [z + 0.06, z + 0.94]) addPost(px, pz, h)
        for (const level of deckLevels) {
          add('decks', [cx, level, cz], [0.88, RACK_DECK_THICKNESS, 0.88])
          if (grid[z - 1]?.[x] !== 1) add('rails', [cx, level, z + 0.06], [0.92, 0.09, 0.065])
          if (grid[z + 1]?.[x] !== 1) add('rails', [cx, level, z + 0.94], [0.92, 0.09, 0.065])
          if (grid[z]?.[x - 1] !== 1) add('rails', [x + 0.06, level, cz], [0.065, 0.09, 0.92])
          if (grid[z]?.[x + 1] !== 1) add('rails', [x + 0.94, level, cz], [0.065, 0.09, 0.92])
          if (level === decorLevel && (x + z) % 2 === 0) {
            add('boxes', [cx, level + 0.23, cz], [0.58, 0.43, 0.60])
            add('tape', [cx, level + 0.448, cz], [0.07, 0.008, 0.61])
          }
        }
      }
      if (cell === 2 && (x === 0 || z === 0)) add('walls', [x + 0.5, 1.35, z + 0.5], [0.98, 2.7, 0.98])
      if (cell !== 1 && cell !== 2 && x > 0 && z > 0) {
        if (grid[z - 1]?.[x] === 1) add('lanes', [x + 0.5, 0.013, z + 0.08], [0.95, 0.006, 0.035])
        if (grid[z + 1]?.[x] === 1) add('lanes', [x + 0.5, 0.013, z + 0.92], [0.95, 0.006, 0.035])
      }
    }
    return result
  }, [warehouse, low])
  const cargo = useMemo(() => mapCargoLifecycle(tasks, robots, warehouse), [tasks, robots, warehouse])
  if (!warehouse) return null
  const { width, height } = warehouse
  const gridDimension = Math.max(width, height)
  const bayPositions = useMemo(() => Array.from(new Set((warehouse.rack_islands || []).map((i) => i.cell[0] + 1))).sort((a, b) => a - b), [warehouse])
  const opacity = shelfView === 'xray' ? 0.18 : 1
  const handling = robots.map((r) => r.handling).filter(Boolean)
  const placing = placeMode && (!sim.running || sim.paused)
  // A unit parked on its pad after the round is still physically docked, so it
  // keeps the pad label and the cable.
  const padOccupant = (x, z) => robots.find((r) => r.charger?.[0] === x && r.charger?.[1] === z && (r.status === 'charging' || r.parked))?.name
  const padClaimant = (x, z) => robots.find((r) => r.charger?.[0] === x && r.charger?.[1] === z && r.status === 'moving_to_charge')?.name
  const zones = warehouse.zones || []
  const exteriorAssets = warehouse.exterior_assets || []
  const markings = warehouse.markings || []
  const hasZones = zones.length > 0
  const enhancedEnvironment = hasZones || exteriorAssets.length > 0
  const apronOrientations = [...new Set(exteriorAssets.map((asset) => asset.orientation || 'south'))]

  return <group>
    {/* Interior clean light-gray concrete warehouse floor */}
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[width / 2, -0.005, height / 2]} receiveShadow>
      <planeGeometry args={[width + (enhancedEnvironment ? 1.2 : 0.8), height + (enhancedEnvironment ? 1.2 : 0.8)]} />
      <meshStandardMaterial color={enhancedEnvironment ? '#e2e8f0' : '#d5dbd8'} roughness={enhancedEnvironment ? 0.65 : 0.86} metalness={enhancedEnvironment ? 0.08 : 0} />
    </mesh>
    {/* Exterior aprons are derived from dock orientation; WH2's south apron is unchanged. */}
    {apronOrientations.map((orientation) => {
      const northSouth = orientation === 'north' || orientation === 'south'
      const position = orientation === 'north'
        ? [width / 2, -0.007, -1.8]
        : orientation === 'south'
          ? [width / 2, -0.007, height + 1.8]
          : orientation === 'west'
            ? [-1.8, -0.007, height / 2]
            : [width + 1.8, -0.007, height / 2]
      return <mesh key={orientation} rotation={[-Math.PI / 2, 0, 0]} position={position} receiveShadow>
        <planeGeometry args={northSouth ? [width + 3.0, 3.8] : [3.8, height + 3.0]} />
        <meshStandardMaterial color="#64748b" roughness={0.88} />
      </mesh>
    })}
    {/* Subtle expansion joints on concrete floor */}
    <gridHelper args={enhancedEnvironment ? [gridDimension, gridDimension, '#cbd5e1', '#e2e8f0'] : [20, 20, '#aebbb9', '#c0cbc7']} position={[width / 2, 0.001, height / 2]} />
    {/* Clean off-white / light industrial wall panels */}
    <Batch items={batches.walls} color="#cbd5e1" />
    {/* High-detail pallet racks: royal industrial blue uprights, safety orange crossbeams */}
    <Batch items={batches.posts} color="#1d4ed8" opacity={opacity} />
    <Batch items={batches.rails} color="#ea580c" opacity={opacity} />
    <Batch items={batches.decks} color="#94a3b8" opacity={opacity} />
    <Batch items={batches.boxes} color="#d4a373" opacity={opacity} />
    <Batch items={batches.tape} color="#b45309" opacity={opacity} />
    <Batch items={batches.lanes} color="#facc15" />
    {!hasZones && bayPositions.map((x, idx) => <group key={x} position={[x, 0, 0.98]}>
      <mesh position={[0, 1.27, 0.04]}><boxGeometry args={[2.5, 2.38, 0.045]} /><meshStandardMaterial color="#8696a5" roughness={0.65} /></mesh>
      {Array.from({ length: 9 }, (_, i) => <mesh key={i} position={[0, 0.2 + i * 0.26, 0.075]}><boxGeometry args={[2.43, 0.02, 0.02]} /><meshStandardMaterial color="#627486" /></mesh>)}
      <Sign at={[0, 1.95, 0.11]} title={`BAY ${idx + 1}`} width={2.1} billboard={false} />
    </group>)}
    {/* Generic 3D Semantic Zones */}
    {zones.map((zone) => {
      if (zone.category === 'storage') {
        return <QuadrantSignAndBollards key={zone.id} zone={zone} />
      }
      if (zone.category === 'sortation') {
        return <SortationLoop key={zone.id} zone={zone} />
      }
      if (zone.category === 'restricted') {
        return <RestrictedZone key={zone.id} zone={zone} />
      }
      if (zone.category === 'charging') {
        const cx = (zone.bounds[0] + zone.bounds[2]) / 2 + 0.5
        const cz = (zone.bounds[1] + zone.bounds[3]) / 2 + 0.5
        return (
          <Sign
            key={zone.id}
            at={[cx, 2.7, cz]}
            title={zone.name}
            subtitle="Inductive AMR Power Depot"
            tone={zone.color}
            width={2.8}
            hang={0.7}
          />
        )
      }
      if (zone.category === 'auxiliary') {
        return <AuxiliaryZone key={zone.id} zone={zone} />
      }
      if (zone.category === 'staging') {
        const cx = (zone.bounds[0] + zone.bounds[2]) / 2 + 0.5
        const cz = (zone.bounds[1] + zone.bounds[3]) / 2 + 0.5
        return (
          <Sign
            key={zone.id}
            at={[cx, 3.4, cz]}
            title={zone.name}
            tone={zone.color}
            width={3.2}
            hang={0.7}
          />
        )
      }
      return null
    })}
    {/* Generic 3D Exterior Assets (Trucks & Dock Doors) */}
    {exteriorAssets.map((asset, i) => {
      if (asset.type === 'freight_truck') {
        return <FreightTruck key={`truck-${i}`} position={asset.position} color={asset.color} orientation={asset.orientation} />
      }
      if (asset.type === 'dock_door') {
        return <DockDoor key={`door-${i}`} position={asset.position} orientation={asset.orientation} />
      }
      return null
    })}
    {/* Generic Roadway Markings */}
    {markings.length > 0 && <RoadwayMarkings markings={markings} />}
    {/* Aisle-side address plate for every rack island in standard warehouse without macro-quadrants */}
    {!hasZones && (warehouse.rack_islands || []).map((island) => <Sign key={island.code} at={[island.cell[0] + 1, low ? 1.12 : 2.52, island.cell[1] + 1]} title={`RACK ${island.code}`} tone="#4a5a8f" width={1.15} />)}
    {/* Live inventory: the reserved slot glows amber at its access cell, the
        stored slot turns green and carries the real package until it is picked. */}
    {liveSlots.map((slot) => <group key={slot.id}>
      <mesh position={[slot.access[0] + 0.5, 0.014, slot.access[1] + 0.5]} rotation={[-Math.PI / 2, 0, 0]}><planeGeometry args={[0.92, 0.92]} /><meshBasicMaterial color={slot.state === 'stored' ? '#297359' : '#b8862c'} transparent opacity={0.22} depthWrite={false} /></mesh>
      {slot.state === 'stored' && cargo.storedCargo.some((item) => item.taskId === slot.task_id) && <CargoBox taskId={slot.task_id} position={rackSlotWorldPosition(slot, shelfView)} />}
    </group>)}
    {(warehouse.tables || []).map((table) => <Station key={table.code} table={table} handling={handling} staged={cargo.tableCargo.find((item) => item.cell[0] === table.cell[0] && item.cell[1] === table.cell[1])} />)}
    {(warehouse.chargers || []).map(([x, z], i) => <ChargerPad key={`c${i}`} cell={[x, z]} index={i} occupant={padOccupant(x, z)} claimant={padClaimant(x, z)} />)}
    {(warehouse.blocked || []).map(([x, z]) => <BlockedAisle key={`${x}:${z}`} position={[x + 0.5, 0, z + 0.5]} cell={[x, z]} />)}
    {placing && <BlockPlacement width={width} height={height} />}
  </group>
}
