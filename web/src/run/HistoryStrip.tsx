import { Link } from 'react-router'
import type { Status } from '../types'
import styles from './HistoryStrip.module.css'

interface HistoryRun {
  id: string
  status: Status
  flaky?: boolean
  title?: string
}

interface Props {
  runs: HistoryRun[]
  // large tiles link to their run; small ones are one image
  size?: 'small' | 'large'
  // small strips pad with ground tiles up to this many, so rows end evenly
  slots?: number
  label?: string
}

// One square per run, oldest first: green passed, sun flaky or live, red failed.
export function HistoryStrip({ runs, size = 'small', slots = 0, label }: Props) {
  if (size === 'small') {
    const empty = Math.max(0, slots - runs.length)
    return (
      <span className={styles.small} role="img" aria-label={label ?? summary(runs)}>
        {runs.map((run) => <span key={run.id} className={`${styles.tile} ${styles[tone(run)]}`} />)}
        {Array.from({ length: empty }, (_, i) => <span key={i} className={`${styles.tile} ${styles.empty}`} />)}
      </span>
    )
  }
  return (
    <ol className={styles.large} aria-label={label ?? summary(runs)}>
      {runs.map((run, i) => (
        <li key={run.id} style={{ animationDelay: `${i * 40}ms` }}>
          <Link to={`/runs/${run.id}`} className={`${styles.tile} ${styles[tone(run)]}`}
            title={describe(run)} aria-label={describe(run)} />
        </li>
      ))}
    </ol>
  )
}

function tone(run: HistoryRun): string {
  if (run.status === 'passed') return run.flaky ? 'flaky' : 'passed'
  if (run.status === 'failed' || run.status === 'error') return 'failed'
  return 'live'
}

function describe(run: HistoryRun): string {
  const status = run.status === 'passed' && run.flaky ? 'passed on retry' : run.status
  return run.title ? `${run.title}, ${status}` : status
}

// "9 of 10 passed, 1 flaky"
function summary(runs: HistoryRun[]): string {
  if (!runs.length) return 'never run'
  const passed = runs.filter((r) => r.status === 'passed').length
  const flaky = runs.filter((r) => r.flaky).length
  return `${passed} of ${runs.length} passed${flaky ? `, ${flaky} flaky` : ''}`
}
