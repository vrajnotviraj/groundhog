import { render, screen, within } from '@testing-library/react'
import type { RunEvent } from '../types'
import { EventLog, groupEvents } from './EventLog'

const at = '2026-10-24T12:00:00Z'
const step = (seq: number, i: number, mode: 'static' | 'failed' = 'static'): RunEvent => ({
  seq, at, kind: 'step', i, id: `s${i}`, description: `step ${i}`, mode, selector: `text="S${i}"`, ms: 120, drift: false, error: null,
})

const FLOW: RunEvent[] = [
  { seq: 1, at, kind: 'note', level: 'info', text: 'flow template-lifecycle' },
  { seq: 2, at, kind: 'case', phase: 'start', case: 'create-sms-template', stage: 'chain' },
  step(3, 1),
  { seq: 4, at, kind: 'shot' },
  step(5, 2),
  { seq: 6, at, kind: 'shot' },
  { seq: 7, at, kind: 'case', phase: 'end', case: 'create-sms-template', stage: 'chain', passed: true },
  { seq: 8, at, kind: 'case', phase: 'start', case: 'delete-sms-template', stage: 'cleanup' },
  step(9, 1, 'failed'),
]

test('groups flow events under the case that ran them, each step with its shot', () => {
  const groups = groupEvents(FLOW)
  expect(groups.map((g) => g.start?.case)).toEqual(['create-sms-template', 'delete-sms-template'])
  expect(groups[0].end?.passed).toBe(true)
  expect(groups[0].rows.map((r) => [r.event.seq, r.shot])).toEqual([[3, 4], [5, 6]])
  expect(groups[1].end).toBeUndefined()
  expect(groups[1].rows.map((r) => r.event.seq)).toEqual([9])
})

test('a single case run has one group without a case header', () => {
  const groups = groupEvents([step(1, 1), { seq: 2, at, kind: 'shot' }])
  expect(groups).toHaveLength(1)
  expect(groups[0].start).toBeUndefined()
})

test('renders case headers with their outcome and the steps beneath them', () => {
  render(<EventLog events={FLOW} onSelectShot={() => {}} />)
  const create = screen.getByText('create-sms-template').closest('div')!.parentElement!
  expect(within(create).getByText('Passed')).toBeInTheDocument()
  expect(screen.getByText('cleanup')).toBeInTheDocument()
  expect(screen.getByText('Running')).toBeInTheDocument()
  expect(screen.getAllByText('step 1')).toHaveLength(2)
})
