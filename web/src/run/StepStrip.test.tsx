import { fireEvent, render, screen } from '@testing-library/react'
import type { Mode } from '../types'
import { StepStrip } from './StepStrip'

const MODES: Mode[] = ['static', 'fallback', 'healed', 'failed', 'skipped']

test('draws one tile per step with its mode class', () => {
  render(<StepStrip modes={MODES} />)
  const strip = screen.getByRole('img')
  expect(strip).toHaveAccessibleName('1 static, 1 fallback, 1 healed, 1 failed, 1 skipped')
  MODES.forEach((mode, i) => expect(strip.children[i]).toHaveClass(mode))
})

test('the large strip numbers its tiles and reports the clicked step', () => {
  const onSelect = vi.fn()
  render(<StepStrip modes={['static', 'healed']} onSelect={onSelect} />)
  fireEvent.click(screen.getByRole('button', { name: 'Step 2, healed' }))
  expect(onSelect).toHaveBeenCalledWith(1)
  expect(screen.getByRole('button', { name: 'Step 1, static' })).toHaveTextContent('1')
})
