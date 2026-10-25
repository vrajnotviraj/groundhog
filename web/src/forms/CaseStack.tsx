import type { FlowCase } from '../types'
import { Button } from './Button'
import { Tile } from '../layout/Tile'
import styles from './CaseStack.module.css'

interface Props {
  title: string
  cases: FlowCase[]
  options: string[]
  onChange: (cases: FlowCase[]) => void
}

// An ordered list of cases that can be reordered, removed and added to.
export function CaseStack({ title, cases, options, onChange }: Props) {
  const move = (from: number, to: number) => {
    const next = [...cases]
    next.splice(to, 0, ...next.splice(from, 1))
    onChange(next)
  }
  return (
    <section className={styles.stack} aria-label={title}>
      <h2>{title}</h2>
      {cases.map((c, i) => (
        <Tile key={`${c.case}-${i}`} className={styles.case}>
          <span className={styles.name}>{c.case}</span>
          {i > 0 && <Button variant="text" onClick={() => move(i, i - 1)}>Up</Button>}
          {i < cases.length - 1 && <Button variant="text" onClick={() => move(i, i + 1)}>Down</Button>}
          <Button variant="quiet" className={styles.remove} onClick={() => onChange(cases.filter((_, j) => j !== i))}>Remove</Button>
        </Tile>
      ))}
      {!cases.length && <Tile tone="ground" className={styles.case}>No cases yet.</Tile>}
      <select aria-label={`Add case to ${title.toLowerCase()}`} value=""
        onChange={(e) => onChange([...cases, { case: e.target.value, vars: {} }])}>
        <option value="">Add a case…</option>
        {options.map((name) => <option key={name} value={name}>{name}</option>)}
      </select>
    </section>
  )
}
