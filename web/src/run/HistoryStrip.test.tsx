import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { HistoryStrip } from './HistoryStrip'

const RUNS = [
  { id: 'a', status: 'passed' as const, flaky: false },
  { id: 'b', status: 'failed' as const, flaky: false },
  { id: 'c', status: 'passed' as const, flaky: true },
]

test('draws one tile per run in its tone, padded with empty tiles', () => {
  render(<HistoryStrip runs={RUNS} slots={10} />)
  const strip = screen.getByRole('img', { name: '2 of 3 passed, 1 flaky' })
  expect(strip.children).toHaveLength(10)
  expect([...strip.children].slice(0, 4).map((tile) => tile.className)).toEqual([
    expect.stringContaining('passed'), expect.stringContaining('failed'), expect.stringContaining('flaky'),
    expect.stringContaining('empty'),
  ])
})

test('the large strip links each run', () => {
  render(<MemoryRouter><HistoryStrip runs={RUNS} size="large" /></MemoryRouter>)
  expect(screen.getByRole('link', { name: 'passed on retry' })).toHaveAttribute('href', '/runs/c')
  expect(screen.getAllByRole('link')).toHaveLength(3)
})
