import { count, duration } from '../format'
import type {
  ActionEvent, AttemptEvent, CaseEvent, DecisionEvent, Mode, PageEvent, RunEvent, Status, StepEvent,
} from '../types'
import { StatusTile } from './StatusTile'
import styles from './EventLog.module.css'

interface Row {
  event: StepEvent | DecisionEvent | ActionEvent | PageEvent
  shot?: number
}

interface Group {
  start?: CaseEvent
  end?: CaseEvent
  attempt: number
  rows: Row[]
}

// The retry the run is on now; undefined while it is on its first attempt.
export const lastAttempt = (events: RunEvent[]) => events.findLast((e): e is AttemptEvent => e.kind === 'attempt')

// Groups rows by attempt and case, each with the screenshot taken after it.
export function groupEvents(events: RunEvent[]): Group[] {
  const groups: Group[] = [{ attempt: 1, rows: [] }]
  for (const event of events) {
    const group = groups[groups.length - 1]
    const last = group.rows[group.rows.length - 1]
    if (event.kind === 'attempt') groups.push({ attempt: event.n, rows: [] })
    else if (event.kind === 'case' && event.phase === 'start') groups.push({ start: event, attempt: group.attempt, rows: [] })
    else if (event.kind === 'case') group.end = event
    else if (event.kind === 'shot' && last && last.shot === undefined) last.shot = event.seq
    else if (event.kind === 'step' || event.kind === 'decision' || event.kind === 'action' || event.kind === 'page') {
      group.rows.push({ event })
    }
  }
  return groups.filter((group) => group.start || group.rows.length)
}

// The final attempt's rows for the step strip (steps, else actions, else pages) and the mode of each.
export function stripOf(events: RunEvent[]): { rows: Row[]; modes: Mode[] } {
  const final = lastAttempt(events)?.n ?? 1
  const all = groupEvents(events).filter((group) => group.attempt === final).flatMap((group) => group.rows)
  const ofKind = (kind: Row['event']['kind']) => all.filter((row) => row.event.kind === kind)
  const rows = [ofKind('step'), ofKind('action'), ofKind('page')].find((list) => list.length) ?? []
  const modes = rows.map(({ event }): Mode => {
    if (event.kind === 'step') return event.mode
    return event.kind === 'action' && !event.ok ? 'failed' : 'static'
  })
  return { rows, modes }
}

interface Props {
  events: RunEvent[]
  // the run's status, shown on the final attempt's header
  status: Status
  onSelectShot: (seq: number) => void
}

// The run page's rows, one seamed block per case; earlier attempts collapse above the final one.
export function EventLog({ events, status, onSelectShot }: Props) {
  const groups = groupEvents(events)
  const final = lastAttempt(events)?.n ?? 1
  const earlier = [...new Set(groups.map((g) => g.attempt))].filter((n) => n < final)
  const finalGroups = groups.filter((g) => g.attempt === final)
  return (
    <div className={styles.log}>
      {earlier.map((n) => (
        <Attempt key={n} n={n} groups={groups.filter((g) => g.attempt === n)} onSelectShot={onSelectShot} />
      ))}
      {earlier.length > 0 && (
        <div className={`${styles.case} ${styles.attemptHead}`}>
          <span className={styles.caseName}>Attempt {final}</span>
          <StatusTile status={finalGroups.some((g) => g.start) ? statusOf(finalGroups) : status} />
        </div>
      )}
      {finalGroups.map((group) => (
        <CaseGroup key={group.start?.seq ?? 0} group={group} onSelectShot={onSelectShot} />
      ))}
    </div>
  )
}

// A flow attempt's status from its case events: failed if any case failed, passed once every case passed.
function statusOf(groups: Group[]): Status {
  if (groups.some((g) => g.end && !g.end.passed)) return 'failed'
  return groups.every((g) => g.end) ? 'passed' : 'running'
}

interface GroupProps {
  group: Group
  onSelectShot: (seq: number) => void
  earlier?: boolean
}

// One case's rows on 2px seams under its header; an earlier attempt's rows are muted, all but its failed step.
function CaseGroup({ group, onSelectShot, earlier = false }: GroupProps) {
  return (
    <div className={styles.group}>
      {group.start && <CaseHeader start={group.start} end={group.end} />}
      {group.rows.map((row) => (
        <EventRow key={row.event.seq} row={row} earlier={earlier} onSelect={() => row.shot && onSelectShot(row.shot)} />
      ))}
    </div>
  )
}

// A failed earlier attempt, collapsed to one row that says where it stopped.
function Attempt({ n, groups, onSelectShot }: { n: number; groups: Group[]; onSelectShot: (seq: number) => void }) {
  const steps = groups.flatMap((g) => g.rows).map((r) => r.event).filter((e): e is StepEvent => e.kind === 'step')
  const failed = steps.find((s) => s.mode === 'failed')
  return (
    <details className={styles.attempt}>
      <summary className={styles.summary}>
        <span className="marker fail">Attempt {n}</span>
        <span>{failed ? `Failed at step ${failed.i} of ${steps.length}` : `Failed after ${count(steps.length, 'step')}`}</span>
        {failed?.error && <span className={`small fail ${styles.clip}`}>{failed.error}</span>}
      </summary>
      {groups.map((group) => <CaseGroup key={group.start?.seq ?? 0} group={group} onSelectShot={onSelectShot} earlier />)}
    </details>
  )
}

function CaseHeader({ start, end }: { start: CaseEvent; end?: CaseEvent }) {
  let status: Status = 'running'
  if (end) status = end.passed ? 'passed' : 'failed'
  return (
    <div className={styles.case}>
      <div className={styles.caseName}>
        <span>{start.case}</span>
        {start.stage === 'cleanup' && <span className="tag">cleanup</span>}
      </div>
      <StatusTile status={status} />
    </div>
  )
}

// The square before a row, in the same tones as the step strip; decisions have none.
function Square({ mode, dim, children }: { mode?: Mode; dim: boolean; children?: number }) {
  if (!mode) return <span />
  return <span className={`${styles.square} ${styles[dim ? 'skipped' : mode]}`}>{children}</span>
}

function EventRow({ row, earlier, onSelect }: { row: Row; earlier: boolean; onSelect: () => void }) {
  const { event } = row
  const dim = earlier && !(event.kind === 'step' ? event.mode === 'failed' : event.kind === 'action' && !event.ok)
  let mode: Mode | undefined
  if (event.kind === 'step') mode = event.mode
  else if (event.kind === 'action') mode = event.ok ? 'static' : 'failed'
  else if (event.kind === 'page') mode = 'static'
  const quiet = dim || (event.kind === 'step' && event.mode === 'skipped')
  return (
    <div id={`event-${event.seq}`} className={`${styles.row} ${quiet ? styles.quiet : ''}`} tabIndex={0}
      onMouseEnter={onSelect} onFocus={onSelect}>
      <Square mode={mode} dim={dim}>{event.kind === 'step' ? event.i : undefined}</Square>
      {event.kind === 'step' && <Step step={event} />}
      {event.kind === 'decision' && <Decision event={event} />}
      {event.kind === 'action' && <Action event={event} />}
      {event.kind === 'page' && <Page event={event} />}
    </div>
  )
}

// One replayed step: what it did, the selector, its mode when not static, and how long it took.
function Step({ step }: { step: StepEvent }) {
  return (
    <>
      <span className={styles.text}>
        <span>
          {step.description}{step.drift && <span className="muted"> (drift)</span>}
          {step.mode !== 'static' && <> <span className={step.mode === 'healed' ? 'tag sun' : 'tag'}>{step.mode}</span></>}
        </span>
        {step.selector && <code className="muted">{step.selector}</code>}
        {step.error && <span className="small fail">{step.error}</span>}
      </span>
      <span className={styles.meta}>{step.ms != null && duration(step.ms)}</span>
    </>
  )
}

function Decision({ event }: { event: DecisionEvent }) {
  return (
    <>
      <span className={styles.text}>
        <span><span className="tag">decision</span> {event.operation.toLowerCase()} <strong>{event.label}</strong></span>
        {event.probability < 0.7 && event.detail && <span className="small muted">{event.detail}</span>}
      </span>
      <span className={styles.meta}>p {event.probability.toFixed(2)}, {event.latency_ms}ms</span>
    </>
  )
}

function Page({ event }: { event: PageEvent }) {
  return (
    <>
      <span className={styles.text}>
        <span>{event.title}</span>
        <code className="muted">{event.path}</code>
      </span>
      <span className={styles.meta}>{count(event.controls, 'control')} · {count(event.links, 'link')}</span>
    </>
  )
}

function Action({ event }: { event: ActionEvent }) {
  return (
    <>
      <span className={styles.text}>
        <span>{event.description}{event.value && <span className="muted"> {event.value}</span>}</span>
        {event.error && <span className="small fail">{event.error}</span>}
      </span>
      <span className={styles.meta}>{event.action}</span>
    </>
  )
}
