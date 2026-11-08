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

// A labelled number tile: the number first, then its label and an optional note.
export function Figure({ label, value, tone = 'surface', note }: Props) {
  return (
    <Tile tone={tone} className={styles.figure} data-tone={tone}>
      <span className={`small ${styles.label}`}>{label}</span>
      {note && <span className={`small ${styles.label}`}>{note}</span>}
      <span className={styles.value}>{value}</span>
    </Tile>
  )
}
