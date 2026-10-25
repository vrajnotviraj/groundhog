import { count, duration } from '../format'
import { Tile, type Tone } from '../layout/Tile'
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

// The run page's rows grouped by case; earlier attempts collapse above the final one.
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
        <div className={styles.case}>
          <Tile tone="surface-2" className={styles.caseName}>Attempt {final}</Tile>
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

// One case's rows; an earlier attempt's rows sit on ground with muted text, all but its failed step.
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
      <summary className={styles.row}>
        <Tile tone="fail" className={styles.kind}>Attempt {n}</Tile>
        <Tile tone="ground" className={styles.body}>
          <span>{failed ? `Failed at step ${failed.i} of ${steps.length}` : `Failed after ${count(steps.length, 'step')}`}</span>
          {failed?.error && <span className={`small fail ${styles.wide} ${styles.clip}`}>{failed.error}</span>}
        </Tile>
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
      <Tile tone="surface-2" className={styles.caseName}>
        <span>{start.case}</span>
        {start.stage === 'cleanup' && <span className="small">cleanup</span>}
      </Tile>
      <StatusTile status={status} />
    </div>
  )
}

const MODE_TONE: Record<Mode, Tone> = {
  static: 'surface', fallback: 'surface-2', healed: 'sun', failed: 'fail', skipped: 'ground',
}

function EventRow({ row, earlier, onSelect }: { row: Row; earlier: boolean; onSelect: () => void }) {
  const { event } = row
  if (event.kind === 'step') return <StepRow step={event} dim={earlier && event.mode !== 'failed'} onSelect={onSelect} />
  let tone: Tone = 'surface'
  if (earlier) tone = 'ground'
  else if (event.kind === 'decision' || event.kind === 'page') tone = 'surface-2'
  else if (!event.ok) tone = 'fail'
  return (
    <div id={`event-${event.seq}`} className={styles.row} tabIndex={0} onMouseEnter={onSelect} onFocus={onSelect}>
      <Tile tone={tone} className={styles.kind}>
        {event.kind}
      </Tile>
      <Tile tone={earlier ? 'ground' : 'surface'} className={earlier ? `${styles.body} muted` : styles.body}>
        {event.kind === 'decision' && <Decision event={event} />}
        {event.kind === 'action' && <Action event={event} />}
        {event.kind === 'page' && <Page event={event} />}
      </Tile>
    </div>
  )
}

// One replayed step: its number in the mode's tone, what it did, the selector and how long it took.
// The mode is spelled out only when it is not static.
function StepRow({ step, dim, onSelect }: { step: StepEvent; dim: boolean; onSelect: () => void }) {
  return (
    <div id={`event-${step.seq}`} className={`${styles.row} ${styles.step}`} tabIndex={0} onMouseEnter={onSelect} onFocus={onSelect}>
      <Tile tone={dim ? 'ground' : MODE_TONE[step.mode]} className={styles.kind}>{step.i}</Tile>
      <Tile tone={dim ? 'ground' : 'surface'} className={dim ? `${styles.stepBody} muted` : styles.stepBody}>
        <span className={styles.text}>
          <span>{step.description}{step.drift && <span className="muted"> (drift)</span>}</span>
          {step.selector && <code className="muted">{step.selector}</code>}
          {step.mode !== 'static' && <span className="small">{step.mode}</span>}
          {step.error && <span className="small fail">{step.error}</span>}
        </span>
        <span className={styles.ms}>{duration(step.ms)}</span>
      </Tile>
    </div>
  )
}

function Decision({ event }: { event: DecisionEvent }) {
  return (
    <>
      <span>{event.operation.toLowerCase()} <strong>{event.label}</strong></span>
      <span className="muted">p {event.probability.toFixed(2)} · {event.latency_ms}ms</span>
      {event.probability < 0.7 && event.detail && <span className={`small muted ${styles.wide}`}>{event.detail}</span>}
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
      <span className="muted">{count(event.controls, 'control')} · {count(event.links, 'link')}</span>
    </>
  )
}

function Action({ event }: { event: ActionEvent }) {
  return (
    <>
      <span>{event.description}{event.value && <span className="muted"> {event.value}</span>}</span>
      <span className="muted">{event.action}</span>
      {event.error && <span className={`small fail ${styles.wide}`}>{event.error}</span>}
    </>
  )
}
