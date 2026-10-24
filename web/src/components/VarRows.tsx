import type { Vars } from '../types'
import { Button } from './Button'
import styles from './VarRows.module.css'

interface Props {
  vars: [string, string][]
  onChange: (vars: [string, string][]) => void
}

// Template vars as editable key/value rows.
export function VarRows({ vars, onChange }: Props) {
  const set = (index: number, pair: [string, string]) => onChange(vars.map((v, i) => (i === index ? pair : v)))
  return (
    <div className={styles.vars}>
      {vars.map(([key, value], i) => (
        <div key={i} className={styles.row}>
          <input aria-label="Var name" placeholder="name" value={key} onChange={(e) => set(i, [e.target.value, value])} />
          <input aria-label={`Value of ${key || 'var'}`} placeholder="value" value={value}
            onChange={(e) => set(i, [key, e.target.value])} />
          <Button variant="text" onClick={() => onChange(vars.filter((_, j) => j !== i))}>Remove</Button>
        </div>
      ))}
      <Button variant="text" onClick={() => onChange([...vars, ['', '']])}>Add var</Button>
    </div>
  )
}

// The rows as a vars object, dropping rows without a name.
export const toVars = (rows: [string, string][]): Vars => Object.fromEntries(rows.filter(([key]) => key.trim()))
