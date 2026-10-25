import { render, screen, within } from '@testing-library/react'
import type { Mode, RunEvent } from '../types'
import { EventLog, groupEvents, stripOf } from './EventLog'

const at = '2026-10-24T12:00:00Z'
const step = (seq: number, i: number, mode: Mode = 'static', error: string | null = null): RunEvent => ({
  seq, at, kind: 'step', i, id: `s${i}`, description: `step ${i}`, mode, selector: `text="S${i}"`, ms: 120, drift: false, error,
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

const RETRIED: RunEvent[] = [
  step(1, 1),
  step(2, 2, 'failed', 'Timed out'),
  step(3, 3, 'skipped'),
  { seq: 4, at, kind: 'attempt', n: 2 },
  step(5, 1),
  { seq: 6, at, kind: 'shot' },
  step(7, 2),
]

test('an attempt event starts a new group and the strip shows the final attempt only', () => {
  expect(groupEvents(RETRIED).map((g) => [g.attempt, g.rows.map((r) => r.event.seq)])).toEqual([[1, [1, 2, 3]], [2, [5, 7]]])
  const { rows, modes } = stripOf(RETRIED)
  expect(rows.map((r) => [r.event.seq, r.shot])).toEqual([[5, 6], [7, undefined]])
  expect(modes).toEqual(['static', 'static'])
})

test('a retry that has not reached a step yet leaves the strip empty', () => {
  expect(stripOf(RETRIED.slice(0, 4)).rows).toEqual([])
})

test('earlier attempts collapse to one row saying where they failed', () => {
  render(<EventLog events={RETRIED} status="failed" onSelectShot={() => {}} />)
  expect(screen.getByText('Attempt 1').closest('details')).not.toHaveAttribute('open')
  expect(screen.getByText('Failed at step 2 of 3')).toBeInTheDocument()
  expect(screen.getByText('Timed out', { selector: 'summary *' })).toBeInTheDocument()
  expect(screen.getByText('Attempt 2').closest('details')).toBeNull()
})

test('the final attempt header shows the run status when no case events exist', () => {
  render(<EventLog events={RETRIED} status="passed" onSelectShot={() => {}} />)
  const header = screen.getByText('Attempt 2').parentElement!
  expect(within(header).getByText('Passed')).toBeInTheDocument()
  expect(screen.queryByText('Running')).toBeNull()
})

test('a crawl lists the pages it stored', () => {
  const page: RunEvent = { seq: 1, at, kind: 'page', path: '/:ws/templates', title: 'Templates', controls: 4, links: 1, depth: 1 }
  render(<EventLog events={[page]} status="passed" onSelectShot={() => {}} />)
  expect(screen.getByText('/:ws/templates')).toBeInTheDocument()
  expect(screen.getByText('4 controls · 1 link')).toBeInTheDocument()
  expect(stripOf([page]).modes).toEqual(['static'])
})

test('renders case headers with their outcome and the steps beneath them', () => {
  render(<EventLog events={FLOW} status="running" onSelectShot={() => {}} />)
  const create = screen.getByText('create-sms-template').closest('div')!.parentElement!
  expect(within(create).getByText('Passed')).toBeInTheDocument()
  expect(screen.getByText('cleanup')).toBeInTheDocument()
  expect(screen.getByText('Running')).toBeInTheDocument()
  expect(screen.getAllByText('step 1')).toHaveLength(2)
})
