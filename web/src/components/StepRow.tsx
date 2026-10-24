import { duration } from '../format'
import type { StepEvent } from '../types'
import { ModeTile } from './ModeTile'
import { Tile } from './Tile'
import styles from './StepRow.module.css'

interface Props {
  step: StepEvent
  onSelect?: () => void
}

// One replayed step: its mode, what it did, the selector it used and how long it took.
export function StepRow({ step, onSelect }: Props) {
  return (
    <div id={`event-${step.seq}`} className={styles.row} tabIndex={0} onMouseEnter={onSelect} onFocus={onSelect}>
      <ModeTile mode={step.mode} />
      <Tile className={styles.body}>
        <span className={styles.index}>{step.i}</span>
        <span className={styles.text}>
          <span>{step.description}{step.drift && <span className="muted"> (drift)</span>}</span>
          {step.selector && <code className="muted">{step.selector}</code>}
          {step.error && <span className="small fail">{step.error}</span>}
        </span>
        <span className={styles.ms}>{duration(step.ms)}</span>
      </Tile>
    </div>
  )
}
