import { act, renderHook, waitFor } from '@testing-library/react'
import { api } from '../api'
import { useRunEvents } from './live'
import type { Run, RunEvent } from '../types'

class FakeEventSource {
  static last: FakeEventSource
  onmessage: ((m: MessageEvent) => void) | null = null
  listeners: Record<string, (m: MessageEvent) => void> = {}
  closed = false
  constructor(public url: string) {
    FakeEventSource.last = this
  }
  addEventListener(name: string, listener: (m: MessageEvent) => void) {
    this.listeners[name] = listener
  }
  close() {
    this.closed = true
  }
  send(data: unknown) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) }))
  }
}

const at = '2026-10-24T12:00:00Z'
const note = (seq: number): RunEvent => ({ seq, at, kind: 'note', level: 'info', text: `line ${seq}` })
const RUN: Run = {
  id: 'abc123def456', kind: 'run', target: 'dashboard-data', vars: {}, status: 'running', created_at: at,
  events: [note(1), note(2)],
}

beforeEach(() => {
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.spyOn(api, 'run').mockResolvedValue(structuredClone(RUN))
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

test('catches up from the document, then appends streamed events in seq order', async () => {
  const { result } = renderHook(() => useRunEvents(RUN.id))
  await waitFor(() => expect(result.current.events).toHaveLength(2))
  const source = FakeEventSource.last
  expect(source.url).toBe('/api/runs/abc123def456/events?after=2')

  act(() => {
    source.send(note(2))
    source.send(note(3))
    source.send(note(1))
    source.send(note(4))
  })
  expect(result.current.events.map((e) => e.seq)).toEqual([1, 2, 3, 4])

  act(() => source.listeners.done(new MessageEvent('done', { data: JSON.stringify({ status: 'passed', total_ms: 3200 }) })))
  expect(result.current.run?.status).toBe('passed')
  expect(source.closed).toBe(true)
})

test('a status event moves a queued run to running before any event arrives', async () => {
  vi.mocked(api.run).mockResolvedValue({ ...RUN, status: 'queued', events: [] })
  const { result } = renderHook(() => useRunEvents(RUN.id))
  await waitFor(() => expect(result.current.run?.status).toBe('queued'))
  act(() => FakeEventSource.last.listeners.status(new MessageEvent('status', { data: JSON.stringify({ status: 'running' }) })))
  expect(result.current.run?.status).toBe('running')
  expect(result.current.events).toHaveLength(0)
})

test('a finished run opens no stream', async () => {
  vi.mocked(api.run).mockResolvedValue({ ...RUN, status: 'passed' })
  const before = FakeEventSource.last
  const { result } = renderHook(() => useRunEvents(RUN.id))
  await waitFor(() => expect(result.current.run?.status).toBe('passed'))
  expect(FakeEventSource.last).toBe(before)
})
