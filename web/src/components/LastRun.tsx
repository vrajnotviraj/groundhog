import { ago } from '../format'
import type { RunRef } from '../types'
import { StepStrip } from './StepStrip'
import styles from './LastRun.module.css'

// A list row's last run: its step strip and when it finished.
export function LastRun({ run }: { run?: RunRef }) {
  if (!run) return <span className="muted">never run</span>
  return (
    <span className={styles.lastRun}>
      <StepStrip modes={run.modes ?? []} />
      <span>{ago(run.finished_at)}</span>
    </span>
  )
}
