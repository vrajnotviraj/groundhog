import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import type { RunOptions } from '../api'
import { Button } from '../forms/Button'
import { Field } from '../forms/Field'
import { toVars, VarRows } from '../forms/VarRows'
import form from '../styles/form.module.css'

interface Props {
  varNames: string[]
  pending: boolean
  error?: string
  onRun: (options: RunOptions) => void
  children?: ReactNode
  title?: string
  onClose?: () => void
  // running several cases at once: no vars, no browser, one sentence instead
  batch?: { cases: number; workers?: number }
}

// The form to start a run with vars, heal, retry and headed; `children` adds fields above the vars.
export function RunForm({ varNames, pending, error, onRun, children, title, onClose, batch }: Props) {
  const [vars, setVars] = useState<[string, string][]>(varNames.map((name) => [name, '']))
  const [heal, setHeal] = useState(true)
  const [retry, setRetry] = useState(Boolean(batch))
  const [headed, setHeaded] = useState(false)
  const self = useRef<HTMLFormElement>(null)
  useEffect(() => self.current?.querySelector<HTMLElement>('input, select')?.focus(), [])
  const submit = (e: FormEvent) => {
    e.preventDefault()
    onRun({ vars: toVars(vars), heal, headed: !batch && headed, retries: retry ? 1 : 0 })
  }
  return (
    <form ref={self} className={`tile ${form.form} ${form.panel}`} onSubmit={submit}>
      {title && (
        <div className={form.head}>
          <h2>{title}</h2>
          {onClose && <Button variant="quiet" onClick={onClose}>Close</Button>}
        </div>
      )}
      {children}
      {batch ? (
        <p>Runs all {batch.cases} cases with fresh vars{batch.workers ? `, ${batch.workers} at a time` : ''}.</p>
      ) : (
        <Field label="Vars" hint="Empty vars get a fresh gh-<stamp> value.">
          <VarRows vars={vars} onChange={setVars} />
        </Field>
      )}
      <label className={form.check}><input type="checkbox" checked={heal} onChange={(e) => setHeal(e.target.checked)} /> Heal broken selectors</label>
      <label className={form.check}><input type="checkbox" checked={retry} onChange={(e) => setRetry(e.target.checked)} /> Retry once on failure</label>
      {!batch && (
        <label className={form.check}><input type="checkbox" checked={headed} onChange={(e) => setHeaded(e.target.checked)} /> Show the browser</label>
      )}
      {error && <p className="fail" role="alert">{error}</p>}
      <Button variant="primary" type="submit" disabled={pending}>{startLabel(pending, batch?.cases)}</Button>
    </form>
  )
}

function startLabel(pending: boolean, cases?: number): string {
  if (pending) return 'Starting'
  return cases ? `Run ${cases} cases` : 'Start run'
}
