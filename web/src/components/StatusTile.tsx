import type { Status } from '../types'
import { Tile, type Tone } from './Tile'
import styles from './StatusTile.module.css'

const TONE: Record<Status, Tone> = { passed: 'pass', failed: 'fail', error: 'fail', running: 'sun', queued: 'surface-2' }
const LABEL: Record<Status, string> = { passed: 'Passed', failed: 'Failed', error: 'Error', running: 'Running', queued: 'Queued' }

// A run's outcome: a coloured dot and its word inside rows, a filled tile as the run page figure.
export function StatusTile({ status, size = 'row' }: { status: Status; size?: 'row' | 'figure' }) {
  if (size === 'row') return <span className={`${styles.status} ${styles.row} ${TONE[status]}`}>{LABEL[status]}</span>
  return <Tile tone={TONE[status]} className={`${styles.status} ${styles.figure}`}>{LABEL[status]}</Tile>
}
