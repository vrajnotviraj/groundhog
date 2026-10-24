import { Tile } from './Tile'
import styles from './Figure.module.css'

// A number with its label above it, zeros printed as 0.
export function Figure({ label, value }: { label: string; value: number | string }) {
  return (
    <Tile className={styles.figure}>
      <span className="small muted">{label}</span>
      <span className={styles.value}>{value}</span>
    </Tile>
  )
}
