import type { Mode } from '../types'
import { Tile, type Tone } from './Tile'
import styles from './ModeTile.module.css'

export const MODE_TONE: Record<Mode, Tone> = {
  static: 'surface', fallback: 'surface-2', healed: 'sun', failed: 'fail', skipped: 'ground',
}

// How a step was replayed, as a tile beside the step.
export function ModeTile({ mode }: { mode: Mode }) {
  return <Tile tone={MODE_TONE[mode]} className={styles.mode}>{mode}</Tile>
}
