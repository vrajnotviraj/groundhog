import { useMutation, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { api } from '../api'
import { Button } from '../components/Button'
import { Field } from '../components/Field'
import { PageTitle } from '../components/PageTitle'
import { Tile } from '../components/Tile'
import { toVars, VarRows } from '../components/VarRows'
import { deriveName, NAME_PATTERN, newest } from '../format'
import styles from '../styles/form.module.css'
import layout from './NewCase.module.css'

export function NewCase() {
  const [intent, setIntent] = useState('')
  const [name, setName] = useState('')
  const [vars, setVars] = useState<[string, string][]>([])
  const [start, setStart] = useState('/:ws/home')
  const [headed, setHeaded] = useState(false)
  const navigate = useNavigate()
  const author = useMutation({
    mutationFn: () => api.authorCase({ intent, name: name || undefined, vars: toVars(vars), start, headed }),
    onSuccess: ({ run_id }) => navigate(`/runs/${run_id}`),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    author.mutate()
  }
  return (
    <>
      <PageTitle title="New case" subline="Jev drives the app once and saves the steps as selectors." />
      <div className={layout.columns}>
        <form className={styles.form} onSubmit={submit}>
          <Field label="Intent" hint={<>Write a value that changes per run as <code>{'{{name}}'}</code> and give it below.</>}>
            <textarea required rows={4} value={intent} onChange={(e) => setIntent(e.target.value)}
              placeholder="Create an SMS template named {{name}} and verify it appears in the templates list" />
          </Field>
          <Field label="Name (optional)" hint={intent && !name ? <>Will be saved as <code>{deriveName(intent)}</code></> : null}>
            <input pattern={NAME_PATTERN} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Vars">
            <VarRows vars={vars} onChange={setVars} />
          </Field>
          <Field label="Start path">
            <input required value={start} onChange={(e) => setStart(e.target.value)} />
          </Field>
          <label className={styles.check}>
            <input type="checkbox" checked={headed} onChange={(e) => setHeaded(e.target.checked)} /> Show the browser
          </label>
          {author.error && <p className="fail" role="alert">{author.error.message}</p>}
          <Button variant="primary" type="submit" disabled={author.isPending}>{author.isPending ? 'Starting' : 'Author the case'}</Button>
        </form>
        <SavedIntents onPick={setIntent} />
      </div>
    </>
  )
}

// The saved cases' intents, newest first; picking one copies it into the form as a starting point.
function SavedIntents({ onPick }: { onPick: (intent: string) => void }) {
  const cases = useQuery({ queryKey: ['cases'], queryFn: api.cases })
  const latest = newest(cases.data ?? [], 10)
  return (
    <Tile className={layout.saved}>
      <h2>Saved intents</h2>
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
