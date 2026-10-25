import type { ReactNode } from 'react'
import { Tile, type Tone } from './Tile'
import styles from './Figure.module.css'

interface Props {
  label: string
  value: number | string
  tone?: Tone
  // a small line under the label
  note?: ReactNode
}

// A labelled number tile: the label and note at the top, the number on the tile's bottom edge.
export function Figure({ label, value, tone, note }: Props) {
  return (
    <Tile tone={tone} className={styles.figure}>
      <span className="small muted">{label}</span>
      {note && <span className="small muted">{note}</span>}
      <span className={styles.value}>{value}</span>
    </Tile>
  )
}
