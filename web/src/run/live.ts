import { useMutation } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { api } from '../api'
import type { Run, RunEvent } from '../types'

export const isLive = (status: Run['status']) => status === 'queued' || status === 'running'

// Adds an event in seq order; a replayed or older event is dropped.
function append(events: RunEvent[], event: RunEvent): RunEvent[] {
  return event.seq > (events.at(-1)?.seq ?? 0) ? [...events, event] : events
}

// Loads a run, then streams its new events and status until it finishes.
export function useRunEvents(runId: string) {
  const [run, setRun] = useState<Run | null>(null)
  const [events, setEvents] = useState<RunEvent[]>([])
  const [error, setError] = useState<Error | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let source: EventSource | undefined
    let closed = false
    setRun(null)
    setEvents([])
    setError(null)
    api.run(runId).then((doc) => {
      if (closed) return
      setRun(doc)
      setEvents(doc.events)
      if (!isLive(doc.status)) return
      source = new EventSource(api.eventsUrl(runId, doc.events.at(-1)?.seq ?? 0), { withCredentials: true })
      source.onmessage = (message) => {
        setEvents((list) => append(list, JSON.parse(message.data)))
      }
      source.addEventListener('status', (message) => {
        const { status } = JSON.parse((message as MessageEvent).data)
        setRun((current) => current && { ...current, status })
      })
      source.addEventListener('done', (message) => {
        setRun((current) => current && { ...current, ...JSON.parse((message as MessageEvent).data) })
        source?.close()
      })
    }, (e: Error) => !closed && setError(e))
    return () => {
      closed = true
      source?.close()
    }
  }, [runId, attempt])

  return { run, events, error, retry: () => setAttempt((n) => n + 1) }
}

// A mutation that starts a run and opens its page.
export function useStartRun<T = void>(start: (input: T) => Promise<{ run_id: string }>) {
  const navigate = useNavigate()
  return useMutation({ mutationFn: start, onSuccess: ({ run_id }) => navigate(`/runs/${run_id}`) })
}
