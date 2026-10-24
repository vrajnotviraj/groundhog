import { Tile } from './Tile'
import styles from './Figure.module.css'

// A labelled number tile.
export function Figure({ label, value }: { label: string; value: number | string }) {
  return (
    <Tile className={styles.figure}>
      <span className="small muted">{label}</span>
      <span className={styles.value}>{value}</span>
    </Tile>
  )
}
