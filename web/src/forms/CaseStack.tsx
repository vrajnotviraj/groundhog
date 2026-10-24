import { useState } from 'react'
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
  const [adding, setAdding] = useState('')
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
          <Button variant="text" disabled={i === 0} onClick={() => move(i, i - 1)}>Up</Button>
          <Button variant="text" disabled={i === cases.length - 1} onClick={() => move(i, i + 1)}>Down</Button>
          <Button variant="quiet" onClick={() => onChange(cases.filter((_, j) => j !== i))}>Remove</Button>
        </Tile>
      ))}
      {!cases.length && <Tile tone="ground" className={styles.case}>No cases yet.</Tile>}
      <div className={styles.add}>
        <select aria-label={`Add case to ${title.toLowerCase()}`} value={adding} onChange={(e) => setAdding(e.target.value)}>
          <option value="">Choose a case</option>
          {options.map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
        <Button variant="text" disabled={!adding} onClick={() => { onChange([...cases, { case: adding, vars: {} }]); setAdding('') }}>
          Add case
        </Button>
      </div>
    </section>
  )
}
