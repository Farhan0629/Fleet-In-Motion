// Pure signage sizing math, kept outside React so it can be regression tested.
export function signPanelWidth(title, minimum = 1.6, maximum = 4.8) {
  const extraCharacters = Math.max(0, String(title || '').length - 12)
  return Math.min(maximum, Math.max(minimum, minimum + extraCharacters * 0.13))
}

export function fitFontSize(ctx, text, startSize, minimumSize, maxWidth, weight = 700) {
  let size = startSize
  do {
    ctx.font = `${weight} ${size}px system-ui, "Segoe UI", Arial, sans-serif`
    if (ctx.measureText(String(text || '')).width <= maxWidth) return size
    size -= 2
  } while (size > minimumSize)
  ctx.font = `${weight} ${minimumSize}px system-ui, "Segoe UI", Arial, sans-serif`
  return minimumSize
}