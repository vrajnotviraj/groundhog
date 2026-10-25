import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { api, isAdmin, meQuery } from '../api'
import { Board } from '../layout/Board'
import { Button } from '../forms/Button'
import { Confirm } from '../forms/Confirm'
import { EventLog, groupEvents, lastAttempt, stripOf } from '../run/EventLog'
import { Figure } from '../layout/Figure'
import { LoadError, LoadingRows } from '../mascot/Loading'
import type { Mood } from '../mascot/Groundhog'
import { Mascot } from '../mascot/Mascot'
import { PageTitle } from '../layout/PageTitle'
import { StatusTile } from '../run/StatusTile'
import { StepStrip } from '../run/StepStrip'
import { Table, type Column } from '../table/Table'
import { Tile } from '../layout/Tile'
import { checkedBy, count, duration, runTitle } from '../format'
import { isLive, useRunEvents } from '../run/live'
import type { AssertionEvent, NoteEvent, Run as RunDoc } from '../types'
import styles from './Run.module.css'

const ASSERTION_COLUMNS: Column<AssertionEvent>[] = [
  {
    header: 'Result', width: '80px', role: 'key',
    cell: (a) => <span className={`marker ${a.passed ? 'pass' : 'fail'}`}>{a.passed ? 'Passed' : 'Failed'}</span>,
  },
  { header: 'Assertion', role: 'identity', width: 'minmax(0, 2fr)', cell: (a) => a.assertion },
  { header: 'Checked by', width: '104px', cell: (a) => checkedBy(a.mode) },
  // Jev's reasoning is only its probability, which the Confidence column already shows
  { header: 'Reasoning', width: 'minmax(0, 3fr)', cell: (a) => (/^jev p=[\d.]+$/.test(a.reasoning) ? null : a.reasoning) },
  { header: 'Confidence', width: '88px', align: 'end', cell: (a) => a.confidence?.toFixed(2) },
]

export function Run() {
  const id = useParams().id!
  const { run, events, error, retry } = useRunEvents(id)
  const [selected, setSelected] = useState<number>()
  const me = useQuery(meQuery)
  const navigate = useNavigate()
  const cancel = useMutation({ mutationFn: () => api.cancelRun(id) })
  const remove = useMutation({ mutationFn: () => api.deleteRun(id), onSuccess: () => navigate('/runs') })

  if (error) return <><PageTitle title="Run" /><LoadError what="this run" onRetry={retry} /></>
  if (!run) return <><PageTitle title="Run" /><LoadingRows /></>

  const live = isLive(run.status)
  const { rows: stripRows, modes } = stripOf(events)
  const newestShot = events.findLast((e) => e.kind === 'shot')?.seq
  const ran = live || groupEvents(events).length > 0
  const retried = lastAttempt(events)
  const assertions = events.filter((e): e is AssertionEvent => e.kind === 'assertion' && e.seq > (retried?.seq ?? 0))

  const jump = (index: number) => {
    const row = stripRows[index]
    document.getElementById(`event-${row.event.seq}`)?.scrollIntoView({ behavior: 'auto', block: 'center' })
    if (row.shot) setSelected(row.shot)
  }

  const actionError = cancel.error ?? remove.error

  return (
    <>
      <PageTitle title={runTitle(run)} subline={<span role="status" aria-atomic="true">{subline(run, stripRows.length)}</span>}>
        {live && <Button variant="primary" disabled={cancel.isPending} onClick={() => cancel.mutate()}>Cancel run</Button>}
        {!live && isAdmin(me.data) && (
          <Confirm label="Delete" question="Delete this run and its screenshots?" onConfirm={() => remove.mutate()} />
        )}
      </PageTitle>
      {actionError && <p className="fail" role="alert">{actionError.message}</p>}
      <div className={styles.headline}>
        <Mascot mood={mood(run.status)} className={styles.mascot} />
        <div className={styles.status}>
          <StatusTile status={run.status} size="figure" />
          {run.flaky && <Tile tone="sun" className={styles.flaky}>flaky · passed on attempt {run.attempts}</Tile>}
        </div>
        {modes.length
          ? <StepStrip modes={modes} onSelect={jump} />
          : <Tile tone="ground" className={styles.waiting}>{waiting(live, retried !== undefined)}</Tile>}
      </div>
      {run.error && <Tile className={styles.runError}><span className="fail">{errorText(run.error, ran)}</span></Tile>}
      {ran && (
        <div className={styles.columns}>
          <div onMouseLeave={() => setSelected(undefined)}><EventLog events={events} status={run.status} onSelectShot={setSelected} /></div>
          <div className={styles.shot}><Screenshot runId={run.id} seq={selected ?? newestShot} /></div>
        </div>
      )}
      {assertions.length > 0 && (
        <Board title="Assertions">
          <Table label="Assertions" columns={ASSERTION_COLUMNS} rows={assertions} rowKey={(a) => String(a.seq)} />
        </Board>
      )}
      {(run.status === 'passed' || run.status === 'failed') && run.kind !== 'crawl' && <Cost run={run} />}
      <Notes notes={events.filter((e): e is NoteEvent => e.kind === 'note')} />
    </>
  )
}

function subline(run: RunDoc, steps: number): string {
  const counted = count(steps, run.kind === 'crawl' ? 'page' : 'step')
  if (isLive(run.status)) return `${run.status} · ${counted} so far`
  const parts = [counted, count(run.ai_calls ?? 0, 'AI call')]
  if (run.total_ms != null) parts.push(duration(run.total_ms))
  if (run.attempts && run.attempts > 1) parts.push(count(run.attempts, 'attempt'))
  return parts.join(' · ')
}

function waiting(live: boolean, retrying: boolean): string {
  if (!live) return 'No steps ran.'
  return retrying ? 'Retrying from step 1.' : 'Waiting for the first step.'
}

function mood(status: RunDoc['status']): Mood {
  if (isLive(status)) return 'dig'
  return status === 'passed' ? 'happy' : 'worried'
}

function errorText(error: string, ran: boolean): string {
  if (error !== 'cancelled') return error
  return ran ? 'Cancelled.' : 'Cancelled before any step ran.'
}

const NOTE_CLASS = { error: 'fail', warn: '', info: 'muted' } as const

// The run's log lines, collapsed.
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

// The run's AI usage, or a note that it used none.
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

// The screenshot taken after a step, or a sentence when there is none yet.
function Screenshot({ runId, seq }: { runId: string; seq?: number }) {
  return (
    <Tile className={styles.screenshot}>
      {seq === undefined
        ? <p className="muted">No screenshot yet.</p>
        : <img src={api.shotUrl(runId, seq)} alt={`Page after event ${seq}`} />}
    </Tile>
  )
}
