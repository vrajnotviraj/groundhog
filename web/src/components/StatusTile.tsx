import type { Status } from '../types'
import { Tile, type Tone } from './Tile'
import styles from './StatusTile.module.css'

const TONE: Record<Status, Tone> = { passed: 'pass', failed: 'fail', error: 'fail', running: 'surface-2', queued: 'surface-2' }
const LABEL: Record<Status, string> = { passed: 'Passed', failed: 'Failed', error: 'Error', running: 'Running', queued: 'Queued' }

// A run's outcome as a coloured tile: compact inside rows, a figure on the run page.
export function StatusTile({ status, size = 'row' }: { status: Status; size?: 'row' | 'figure' }) {
  return <Tile tone={TONE[status]} className={`${styles.status} ${styles[size]}`}>{LABEL[status]}</Tile>
}
