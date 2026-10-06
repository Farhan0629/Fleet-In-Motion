import test from 'node:test'
import assert from 'node:assert/strict'
import { fitFontSize, signPanelWidth } from '../utils/signage.js'

test('short labels preserve their requested panel width', () => {
  assert.equal(signPanelWidth('RACK A', 2.2), 2.2)
})

test('long labels widen without exceeding the scene-safe maximum', () => {
  const width = signPanelWidth('RETURNS & REVERSE LOGISTICS', 1.8)
  assert.ok(width > 1.8)
  assert.ok(width <= 4.8)
})

test('font fitting reduces oversized text until it fits the canvas', () => {
  const context = {
    font: '',
    measureText(text) {
      const size = Number(this.font.match(/(\d+)px/)?.[1] || 0)
      return { width: text.length * size }
    },
  }
  const size = fitFontSize(context, 'AUTOMATED STORAGE', 58, 30, 520)
  assert.ok(size < 58)
  assert.ok(context.measureText('AUTOMATED STORAGE').width <= 520)
})