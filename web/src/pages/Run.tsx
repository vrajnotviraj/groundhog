import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { api } from '../api'
import { Board } from '../components/Board'
import { Button } from '../components/Button'
import { Confirm } from '../components/Confirm'
import { EventLog, groupEvents, stripOf } from '../components/EventLog'
import { Figure } from '../components/Figure'
import { LoadError, LoadingRows } from '../components/Loading'
import type { Mood } from '../components/Groundhog'
import { Mascot } from '../components/Mascot'
import { PageTitle } from '../components/PageTitle'
import { Shot } from '../components/Shot'
import { StatusTile } from '../components/StatusTile'
import { StepStrip } from '../components/StepStrip'
import { Table, type Column } from '../components/Table'
import { Tile } from '../components/Tile'
import { count, duration, runTitle } from '../format'
import { isLive, useRunEvents } from '../live'
import type { AssertionEvent, NoteEvent, Run as RunDoc } from '../types'
import styles from './Run.module.css'

const ASSERTION_COLUMNS: Column<AssertionEvent>[] = [
  { header: 'Result', width: '80px', role: 'key', cell: (a) => (a.passed ? 'Passed' : <span className="fail">Failed</span>) },
  { header: 'Assertion', role: 'identity', width: 'minmax(0, 2fr)', cell: (a) => a.assertion },
  { header: 'Checked by', width: '104px', cell: (a) => (a.mode === 'jev' ? 'Jev' : 'deterministic') },
  { header: 'Reasoning', width: 'minmax(0, 3fr)', cell: (a) => a.reasoning },
  { header: 'Confidence', width: '88px', align: 'end', cell: (a) => a.confidence?.toFixed(2) },
]

export function Run() {
  const id = useParams().id!
  const { run, events, error, retry } = useRunEvents(id)
  const [selected, setSelected] = useState<number>()
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })
  const navigate = useNavigate()
  const cancel = useMutation({ mutationFn: () => api.cancelRun(id) })
  const remove = useMutation({ mutationFn: () => api.deleteRun(id), onSuccess: () => navigate('/runs') })

  if (error) return <><PageTitle title="Run" /><LoadError what="this run" onRetry={retry} /></>
  if (!run) return <><PageTitle title="Run" /><LoadingRows /></>

  const live = isLive(run.status)
  const { rows: stripRows, modes } = stripOf(events)
  const newestShot = events.findLast((e) => e.kind === 'shot')?.seq
  const ran = live || groupEvents(events).length > 0
  const assertions = events.filter((e): e is AssertionEvent => e.kind === 'assertion')

  const jump = (index: number) => {
    const row = stripRows[index]
    document.getElementById(`event-${row.event.seq}`)?.scrollIntoView({ behavior: 'auto', block: 'center' })
    if (row.shot) setSelected(row.shot)
  }

  const actionError = cancel.error ?? remove.error

  return (
    <>
      <PageTitle title={runTitle(run)} subline={subline(run, stripRows.length)}>
        {live && <Button variant="primary" disabled={cancel.isPending} onClick={() => cancel.mutate()}>Cancel run</Button>}
        {!live && me.data?.role === 'admin' && (
          <Confirm label="Delete" question="Delete this run and its screenshots?" onConfirm={() => remove.mutate()} />
        )}
      </PageTitle>
      {actionError && <p className="fail" role="alert">{actionError.message}</p>}
      <div className={styles.headline}>
        <Mascot mood={mood(run.status)} className={styles.mascot} />
        <StatusTile status={run.status} size="figure" />
        {modes.length
          ? <StepStrip modes={modes} size="large" onSelect={jump} />
          : <Tile tone="ground" className={styles.waiting}>{live ? 'Waiting for the first step.' : 'No steps ran.'}</Tile>}
      </div>
      {run.error && <Tile className={styles.runError}><span className="fail">{errorText(run.error, ran)}</span></Tile>}
      {ran && (
        <div className={styles.columns}>
          <div onMouseLeave={() => setSelected(undefined)}><EventLog events={events} onSelectShot={setSelected} /></div>
          <div className={styles.shot}><Shot runId={run.id} seq={selected ?? newestShot} /></div>
        </div>
      )}
      {assertions.length > 0 && (
        <Board title="Assertions">
          <Table label="Assertions" columns={ASSERTION_COLUMNS} rows={assertions} rowKey={(a) => String(a.seq)} />
        </Board>
      )}
      {(run.status === 'passed' || run.status === 'failed') && <Cost run={run} />}
      <Notes notes={events.filter((e): e is NoteEvent => e.kind === 'note')} />
    </>
  )
}

function subline(run: RunDoc, steps: number): string {
  if (isLive(run.status)) return `${run.status} · ${count(steps, 'step')} so far`
  const parts = [count(steps, 'step'), count(run.ai_calls ?? 0, 'AI call')]
  if (run.total_ms != null) parts.push(duration(run.total_ms))
  return parts.join(' · ')
}

function mood(status: RunDoc['status']): Mood {
  if (isLive(status)) return 'dig'
  return status === 'passed' ? 'happy' : 'worried'
}

function errorText(error: string, ran: boolean): string {
  if (error !== 'cancelled') return error
  return ran ? 'Cancelled.' : 'Cancelled before any step ran.'
}

// Every line the run printed, folded away.
const NOTE_CLASS = { error: 'fail', warn: '', info: 'muted' } as const

function Notes({ notes }: { notes: NoteEvent[] }) {
  if (!notes.length) return null
  return (
    <details className={styles.notes}>
      <summary>Everything the run said <span className="muted">{count(notes.length, 'line')}</span></summary>
      {notes.map((note) => (
        <p key={note.seq} className={NOTE_CLASS[note.level]}>{note.text}</p>
      ))}
    </details>
  )
}

// What the run spent on AI, or one tile saying it spent nothing.
function Cost({ run }: { run: RunDoc }) {
  const { jev, anthropic } = run.usage ?? {}
  if (!jev && !anthropic) return <Tile className={styles.static}>Zero AI calls, fully static run.</Tile>
  return (
    <Board title="AI cost" className={styles.cost}>
      {jev && <Figure label="Jev calls" value={jev.calls} />}
      {jev && <Figure label="Jev input tokens" value={jev.input_tokens.toLocaleString('en')} />}
      {jev && <Figure label="Jev latency" value={duration(jev.latency_ms)} />}
      {anthropic && <Figure label="Anthropic calls" value={anthropic.calls} />}
      {anthropic && <Figure label="Anthropic tokens" value={(anthropic.input_tokens + anthropic.output_tokens).toLocaleString('en')} />}
    </Board>
  )
}
