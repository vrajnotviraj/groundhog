// useRunEvents: the run document, then its new events as the worker writes them.
import { useEffect, useState } from 'react'
import { api } from './api'
import type { Run, RunEvent } from './types'

export const isLive = (status: Run['status']) => status === 'queued' || status === 'running'

// Keeps events in seq order; a replayed or older event is dropped.
export function append(events: RunEvent[], event: RunEvent): RunEvent[] {
  return event.seq > (events.at(-1)?.seq ?? 0) ? [...events, event] : events
}

export function useRunEvents(runId: string) {
  const [run, setRun] = useState<Run | null>(null)
  const [events, setEvents] = useState<RunEvent[]>([])
  const [done, setDone] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let source: EventSource | undefined
    let closed = false
    setRun(null)
    setEvents([])
    setDone(false)
    setError(null)
    api.run(runId).then((doc) => {
      if (closed) return
      setRun(doc)
      setEvents(doc.events)
      setDone(!isLive(doc.status))
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
        setDone(true)
        source?.close()
      })
    }, (e: Error) => !closed && setError(e))
    return () => {
      closed = true
      source?.close()
    }
  }, [runId, attempt])

  return { run, events, done, error, retry: () => setAttempt((n) => n + 1) }
}
