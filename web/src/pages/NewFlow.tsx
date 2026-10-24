import { useMutation, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { api, casesQuery, settingsHealthQuery } from '../api'
import { Board } from '../layout/Board'
import { Button } from '../forms/Button'
import { CaseStack } from '../forms/CaseStack'
import { Field } from '../forms/Field'
import { PageTitle } from '../layout/PageTitle'
import { toVars, VarRows } from '../forms/VarRows'
import { NAME_PATTERN } from '../format'
import { useStartRun } from '../run/live'
import form from '../styles/form.module.css'
import type { FlowCase } from '../types'
import styles from './NewFlow.module.css'

export function NewFlow() {
  return (
    <>
      <PageTitle title="New flow" subline="A flow runs saved cases in order in one browser, then its cleanup." />
      <Board className={styles.two}>
        <Compose />
        <ByHand />
      </Board>
    </>
  )
}

function Compose() {
  const [intent, setIntent] = useState('')
  const health = useQuery(settingsHealthQuery)
  const compose = useStartRun(() => api.composeFlow({ intent }))
  const keySet = health.data?.optional.find((o) => o.name.includes('ANTHROPIC'))?.set
  const submit = (e: FormEvent) => {
    e.preventDefault()
    compose.mutate()
  }
  return (
    <form className={`tile ${form.form} ${form.panel}`} onSubmit={submit}>
      <h2>Compose from English</h2>
      <Field label="What the flow does" hint="Saved cases are reused; missing ones are authored.">
        <textarea required rows={6} value={intent} onChange={(e) => setIntent(e.target.value)}
          placeholder="Create an SMS template, find it in the templates list, then delete it" />
      </Field>
      {keySet === false && <p className="muted">Composing needs <code>ANTHROPIC_API_KEY</code> in <code>.env</code>.</p>}
      {compose.error && <p className="fail" role="alert">{compose.error.message}</p>}
      <Button variant="primary" type="submit" disabled={keySet === false || compose.isPending}>Compose</Button>
    </form>
  )
}

function ByHand() {
  const [name, setName] = useState('')
  const [vars, setVars] = useState<[string, string][]>([])
  const [chain, setChain] = useState<FlowCase[]>([])
  const [cleanup, setCleanup] = useState<FlowCase[]>([])
  const cases = useQuery(casesQuery)
  const names = (cases.data ?? []).map((c) => c.name)
  const navigate = useNavigate()
  const save = useMutation({
    mutationFn: () => api.saveFlow(name, {
      name, intent: '', vars: toVars(vars), chain, cleanup,
    }),
    onSuccess: () => navigate(`/flows/${name}`),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <form className={`tile ${form.form} ${form.panel}`} onSubmit={submit}>
      <h2>Build by hand</h2>
      <Field label="Name">
        <input required pattern={NAME_PATTERN} value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Shared vars"><VarRows vars={vars} onChange={setVars} /></Field>
      <CaseStack title="Chain" cases={chain} options={names} onChange={setChain} />
      <CaseStack title="Cleanup" cases={cleanup} options={names} onChange={setCleanup} />
      {save.error && <p className="fail" role="alert">{save.error.message}</p>}
      <Button variant="primary" type="submit" disabled={!chain.length || save.isPending}>Save flow</Button>
    </form>
  )
}
