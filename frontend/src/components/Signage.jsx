import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { CanvasTexture, DoubleSide, SRGBColorSpace, Vector3 } from 'three'
import { fitFontSize, signPanelWidth } from '../utils/signage.js'

/**
 * In-world 3D signage.
 *
 * The floor used to carry an HTML label over every table, charger and bay.
 * HTML overlays ignore depth, keep a constant screen size and stack on top of
 * each other, which is why the view filled up with white cards. These signs are
 * real geometry instead: text painted into a canvas texture on a plane, so a
 * sign sits in the scene, is occluded by racks, shrinks with distance and never
 * covers the dashboard. Text is drawn with the system font stack, so nothing is
 * fetched over the network.
 */
const SIGN_W = 512
const SIGN_H = 160

export function drawSign(title, subtitle, tone) {
  const canvas = document.createElement('canvas')
  canvas.width = SIGN_W
  canvas.height = SIGN_H
  const ctx = canvas.getContext('2d')
  ctx.fillStyle = '#f8fafc'
  ctx.fillRect(0, 0, SIGN_W, SIGN_H)
  ctx.fillStyle = tone
  ctx.fillRect(0, 0, SIGN_W, 14)
  ctx.fillRect(0, SIGN_H - 14, SIGN_W, 14)
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = '#1b2735'
  fitFontSize(ctx, title, subtitle ? 58 : 72, subtitle ? 34 : 40, SIGN_W - 38, 700)
  ctx.fillText(title, SIGN_W / 2, subtitle ? 66 : SIGN_H / 2)
  if (subtitle) {
    ctx.fillStyle = '#5b6b7d'
    fitFontSize(ctx, subtitle, 38, 24, SIGN_W - 34, 400)
    ctx.fillText(subtitle, SIGN_W / 2, 118)
  }
  const texture = new CanvasTexture(canvas)
  texture.anisotropy = 4
  texture.colorSpace = SRGBColorSpace
  return texture
}

/**
 * A sign panel. `hang` draws suspension rods above the panel so station signs
 * read as hung from the roof, which keeps the aisles clear of posts. Signs
 * billboard around their vertical axis so they stay legible from any camera
 * preset; wall-mounted signs pass `billboard={false}`.
 */
export default function Sign({ at = [0, 0, 0], title, subtitle = '', tone = '#254f82', width = 1.6, maxWidth = 4.8, autoWidth = true, hang = 0, billboard = true, rotationY = 0 }) {
  const group = useRef()
  const world = useMemo(() => new Vector3(), [])
  const texture = useMemo(() => drawSign(title, subtitle, tone), [title, subtitle, tone])
  const panelWidth = autoWidth ? signPanelWidth(title, width, maxWidth) : width
  useEffect(() => () => texture.dispose(), [texture])
  useFrame(({ camera }) => {
    if (!billboard || !group.current) return
    group.current.getWorldPosition(world)
    group.current.rotation.y = Math.atan2(camera.position.x - world.x, camera.position.z - world.z)
  })
  const height = (panelWidth * SIGN_H) / SIGN_W
  return <group ref={group} position={at} rotation={[0, rotationY, 0]}>
    <mesh position={[0, 0, -0.012]}><planeGeometry args={[panelWidth + 0.05, height + 0.05]} /><meshBasicMaterial color={tone} side={DoubleSide} toneMapped={false} /></mesh>
    <mesh><planeGeometry args={[panelWidth, height]} /><meshBasicMaterial map={texture} side={DoubleSide} toneMapped={false} /></mesh>
    {hang > 0 && [-panelWidth * 0.3, panelWidth * 0.3].map((dx) => (
      <mesh key={dx} position={[dx, height / 2 + hang / 2, -0.012]}><boxGeometry args={[0.022, hang, 0.022]} /><meshStandardMaterial color="#7c8b9a" metalness={0.4} roughness={0.5} /></mesh>
    ))}
  </group>
}
