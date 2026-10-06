import { Suspense, useMemo } from 'react'
import { Canvas } from '@react-three/fiber'
import { Object3D } from 'three'
import useStore from '../store'
import Warehouse from './Warehouse'
import Robots from './Robots'
import CameraController from './CameraController'
export default function Scene() {
  const warehouse = useStore((s) => s.warehouse)
  const cx = (warehouse?.width ?? 20) / 2
  const cz = (warehouse?.height ?? 20) / 2
  const maxDim = Math.max(warehouse?.width ?? 20, warehouse?.height ?? 20)
  const enhancedEnvironment = (warehouse?.zones?.length ?? 0) > 0 || (warehouse?.exterior_assets?.length ?? 0) > 0
  const shadowSpan = Math.max(22, maxDim * 0.85)
  const lightTarget = useMemo(() => { const target = new Object3D(); target.position.set(cx, 0.4, cz); return target }, [cx, cz])

  // Elevated architectural isometric viewpoint: looking down at ~40 degrees from high above
  const initialCamPos = useMemo(() => [
    cx + maxDim * 0.45,
    maxDim * 1.35,
    cz + maxDim * 1.25
  ], [cx, cz, maxDim])

  return <Canvas shadows camera={{ position: initialCamPos, fov: 38, near: 0.1, far: 350 }} dpr={[1, 1.5]} gl={{ antialias: true, alpha: false }} fallback={<div className="scene-message">WebGL is unavailable. The live dashboard remains usable.</div>}>
    <color attach="background" args={[enhancedEnvironment ? '#e8edf2' : '#e5ebe8']} />
    <Suspense fallback={null}>
      {/* Bright, high-illumination industrial warehouse lighting */}
      <ambientLight intensity={enhancedEnvironment ? 1.05 : 0.75} color="#ffffff" />
      <hemisphereLight args={enhancedEnvironment ? ['#ffffff', '#cbd5e1', 0.85] : ['#ffffff', '#92a298', 0.65]} />
      <primitive object={lightTarget} />
      {enhancedEnvironment ? <>
        {/* Primary overhead industrial daylight with soft shadows */}
        <directionalLight
          position={[cx + 14, maxDim * 1.8, cz + 16]}
          target={lightTarget}
          intensity={1.75}
          castShadow
          shadow-mapSize={[2048, 2048]}
          shadow-camera-left={-shadowSpan}
          shadow-camera-right={shadowSpan}
          shadow-camera-top={shadowSpan}
          shadow-camera-bottom={-shadowSpan}
          shadow-camera-near={1}
          shadow-camera-far={maxDim * 3.5}
          shadow-bias={-0.0003}
          shadow-normalBias={0.03}
        />
        {/* Soft secondary fill light from opposite corner to keep all aisles brightly lit */}
        <directionalLight
          position={[cx - 16, maxDim * 1.4, cz - 16]}
          target={lightTarget}
          intensity={0.65}
          color="#f1f5f9"
        />
      </> : <directionalLight
        position={[5, 24, 15]}
        target={lightTarget}
        intensity={1.65}
        castShadow
        shadow-mapSize={[1024, 1024]}
        shadow-camera-left={-16}
        shadow-camera-right={16}
        shadow-camera-top={16}
        shadow-camera-bottom={-16}
        shadow-camera-near={1}
        shadow-camera-far={60}
        shadow-bias={-0.0004}
        shadow-normalBias={0.025}
      />}
      <Warehouse /><Robots /><CameraController />
    </Suspense>
  </Canvas>
}
