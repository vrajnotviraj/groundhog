import type { ActionEvent, CaseEvent, DecisionEvent, Mode, RunEvent, Status, StepEvent } from '../types'
import { StatusTile } from './StatusTile'
import { StepRow } from './StepRow'
import { Tile, type Tone } from './Tile'
import styles from './EventLog.module.css'

export interface Row {
  event: StepEvent | DecisionEvent | ActionEvent
  shot?: number
}

export interface Group {
  start?: CaseEvent
  end?: CaseEvent
  rows: Row[]
}

// Steps, decisions and actions under the case that ran them, each with the shot taken after it.
export function groupEvents(events: RunEvent[]): Group[] {
  const groups: Group[] = [{ rows: [] }]
  for (const event of events) {
    const group = groups[groups.length - 1]
    const last = group.rows[group.rows.length - 1]
    if (event.kind === 'case' && event.phase === 'start') groups.push({ start: event, rows: [] })
    else if (event.kind === 'case') group.end = event
    else if (event.kind === 'shot' && last && last.shot === undefined) last.shot = event.seq
    else if (event.kind === 'step' || event.kind === 'decision' || event.kind === 'action') group.rows.push({ event })
  }
  return groups.filter((group) => group.start || group.rows.length)
}

// The rows the step strip shows (the steps, or the actions when there are none) and the mode of each.
export function stripOf(events: RunEvent[]): { rows: Row[]; modes: Mode[] } {
  const all = groupEvents(events).flatMap((group) => group.rows)
  const steps = all.filter((row) => row.event.kind === 'step')
  const rows = steps.length ? steps : all.filter((row) => row.event.kind === 'action')
  const modes = rows.map(({ event }): Mode => {
    if (event.kind === 'step') return event.mode
    return event.kind === 'action' && !event.ok ? 'failed' : 'static'
  })
  return { rows, modes }
}

interface Props {
  events: RunEvent[]
  onSelectShot: (seq: number) => void
}

// The live step list of a run page.
export function EventLog({ events, onSelectShot }: Props) {
  return (
    <div className={styles.log}>
      {groupEvents(events).map((group) => (
        <div key={group.start?.seq ?? 0} className={styles.group}>
          {group.start && <CaseHeader start={group.start} end={group.end} />}
          {group.rows.map((row) => (
            <EventRow key={row.event.seq} row={row} onSelect={() => row.shot && onSelectShot(row.shot)} />
          ))}
        </div>
      ))}
    </div>
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

function EventRow({ row, onSelect }: { row: Row; onSelect: () => void }) {
  const { event } = row
  if (event.kind === 'step') return <StepRow step={event} onSelect={onSelect} />
  let tone: Tone = 'surface'
  if (event.kind === 'decision') tone = 'surface-2'
  else if (!event.ok) tone = 'fail'
  return (
    <div id={`event-${event.seq}`} className={styles.row} tabIndex={0} onMouseEnter={onSelect} onFocus={onSelect}>
      <Tile tone={tone} className={styles.kind}>
        {event.kind}
      </Tile>
      <Tile className={styles.body}>
        {event.kind === 'decision' ? <Decision event={event} /> : <Action event={event} />}
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

function Action({ event }: { event: ActionEvent }) {
  return (
    <>
      <span>{event.description}{event.value && <span className="muted"> {event.value}</span>}</span>
      <span className="muted">{event.action}</span>
      {event.error && <span className={`small fail ${styles.wide}`}>{event.error}</span>}
    </>
  )
}
