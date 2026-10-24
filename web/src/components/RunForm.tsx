import { useState, type FormEvent, type ReactNode } from 'react'
import type { RunOptions } from '../api'
import { Button } from './Button'
import { Field } from './Field'
import { toVars, VarRows } from './VarRows'
import form from '../styles/form.module.css'

interface Props {
  varNames: string[]
  pending: boolean
  error?: string | null
  onRun: (options: RunOptions) => void
  children?: ReactNode
}

// Vars, heal and headed for one run; `children` adds fields above the vars (the overview's case picker).
export function RunForm({ varNames, pending, error, onRun, children }: Props) {
  const [vars, setVars] = useState<[string, string][]>(varNames.map((name) => [name, '']))
  const [heal, setHeal] = useState(true)
  const [headed, setHeaded] = useState(false)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    onRun({ vars: toVars(vars), heal, headed })
  }
  return (
    <form className={`tile ${form.form} ${form.panel}`} onSubmit={submit}>
      {children}
      <Field label="Vars" hint="Empty vars get a fresh gh-<stamp> value.">
        <VarRows vars={vars} onChange={setVars} />
      </Field>
      <label className={form.check}><input type="checkbox" checked={heal} onChange={(e) => setHeal(e.target.checked)} /> Heal broken selectors</label>
      <label className={form.check}><input type="checkbox" checked={headed} onChange={(e) => setHeaded(e.target.checked)} /> Show the browser</label>
      {error && <p className="fail">{error}</p>}
      <Button variant="primary" type="submit" disabled={pending}>{pending ? 'Starting' : 'Start run'}</Button>
    </form>
  )
}
