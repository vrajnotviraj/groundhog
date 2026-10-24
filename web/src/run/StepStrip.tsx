import type { Mode } from '../types'
import styles from './StepStrip.module.css'

interface Props {
  modes: Mode[]
  onSelect?: (index: number) => void
}

// One tile per step, coloured by mode; clickable and numbered when `onSelect` is set.
export function StepStrip({ modes, onSelect }: Props) {
  if (!onSelect) {
    return (
      <span className={styles.small} role="img" aria-label={summary(modes)}>
        {modes.map((mode, i) => <span key={i} className={`${styles.tile} ${styles[mode]}`} />)}
      </span>
    )
  }
  return (
    <div className={styles.large}>
      {modes.map((mode, i) => (
        <button key={i} type="button" className={`${styles.tile} ${styles[mode]}`}
          aria-label={`Step ${i + 1}, ${mode}`} onClick={() => onSelect(i)}>
          {i + 1}
        </button>
      ))}
    </div>
  )
}

function summary(modes: Mode[]): string {
  if (!modes.length) return 'no steps'
  const counts = new Map<Mode, number>()
  modes.forEach((mode) => counts.set(mode, (counts.get(mode) ?? 0) + 1))
  return [...counts].map(([mode, n]) => `${n} ${mode}`).join(', ')
}
