import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, casesQuery } from '../api'
import { Button } from '../forms/Button'
import { Field } from '../forms/Field'
import { PageTitle } from '../layout/PageTitle'
import { Tile } from '../layout/Tile'
import { toVars, VarRows } from '../forms/VarRows'
import { deriveName, intentVars, NAME_PATTERN, newest } from '../format'
import { useStartRun } from '../run/live'
import styles from '../styles/form.module.css'
import layout from './NewCase.module.css'

export function NewCase() {
  const [intent, setIntent] = useState('')
  const [name, setName] = useState('')
  const [vars, setVars] = useState<[string, string][]>([])
  const [start, setStart] = useState('/:ws/home')
  const [headed, setHeaded] = useState(false)
  const author = useStartRun(() => api.authorCase({ intent, name: name || undefined, vars: toVars(vars), start, headed }))
  const submit = (e: FormEvent) => {
    e.preventDefault()
    author.mutate()
  }
  // a {{var}} the intent declares gets an empty row, so the user only types its value
  const changeIntent = (next: string) => {
    setIntent(next)
    setVars((rows) => [...rows, ...intentVars(next).filter((v) => !rows.some(([key]) => key === v)).map((v): [string, string] => [v, ''])])
  }
  return (
    <>
      <PageTitle title="New case" subline="Jev drives the app once and saves the steps as selectors." />
      <div className="split">
        <form className={styles.form} onSubmit={submit}>
          <Field label="Intent" hint={<>Write a value that changes per run as <code>{'{{name}}'}</code> and give it below.</>}>
            <textarea required rows={5} value={intent} onChange={(e) => changeIntent(e.target.value)}
              placeholder="Create an SMS template named {{name}} and verify it appears in the templates list" />
          </Field>
          <div className="split">
            <Field label="Name (optional)" hint={intent && !name ? <>Will be saved as <code>{deriveName(intent)}</code></> : null}>
              <input pattern={NAME_PATTERN} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Start path" hint={<>Where Jev starts, relative to the workspace. <code>/:ws/home</code> is the dashboard.</>}>
              <input required value={start} onChange={(e) => setStart(e.target.value)} />
            </Field>
          </div>
          <Field label="Vars">
            <VarRows vars={vars} onChange={setVars} />
          </Field>
          <label className={styles.check}>
            <input type="checkbox" checked={headed} onChange={(e) => setHeaded(e.target.checked)} /> Show the browser
          </label>
          {author.error && <p className="fail" role="alert">{author.error.message}</p>}
          <div className={styles.actions}>
            <Button variant="primary" type="submit" disabled={author.isPending}>{author.isPending ? 'Starting' : 'Author the case'}</Button>
            <span className="small muted">Takes about a minute. You'll watch it on the run page.</span>
          </div>
        </form>
        <SavedIntents onPick={changeIntent} />
      </div>
    </>
  )
}

// The newest saved intents; picking one copies it into the form.
function SavedIntents({ onPick }: { onPick: (intent: string) => void }) {
  const cases = useQuery(casesQuery)
  const latest = newest(cases.data ?? [], 10)
  return (
    <Tile className={layout.saved}>
      <h2>Start from a saved intent</h2>
      {cases.data && !latest.length && <p className="muted">No saved cases yet.</p>}
      {latest.map((c) => (
        <button key={c.name} type="button" className={layout.intent} onClick={() => onPick(c.intent)}>
          <span className={`${layout.line} ${layout.name}`}>{c.name}</span>
          <span className={`small muted ${layout.line}`}>{c.intent}</span>
        </button>
      ))}
    </Tile>
  )
}
