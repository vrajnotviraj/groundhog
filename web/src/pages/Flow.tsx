import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { api } from '../api'
import { Board } from '../components/Board'
import { Button } from '../components/Button'
import { CaseStack } from '../components/CaseStack'
import { Confirm } from '../components/Confirm'
import { Empty } from '../components/Empty'
import { LoadError, LoadingRows } from '../components/Loading'
import { PageTitle } from '../components/PageTitle'
import { RunTable } from '../components/RunTable'
import { toVars, VarRows } from '../components/VarRows'
import type { FlowDetail } from '../types'
import styles from './Flow.module.css'

export function Flow() {
  const name = useParams().name!
  const detail = useQuery({ queryKey: ['flow', name], queryFn: () => api.flow(name) })
  if (detail.isError) return <><PageTitle title={name} /><LoadError what="this flow" onRetry={detail.refetch} /></>
  if (!detail.data) return <><PageTitle title={name} /><LoadingRows /></>
  return <Builder key={detail.data.updated_at} flow={detail.data} />
}

// The flow's chain, cleanup and shared vars, edited in place and saved as one document.
function Builder({ flow }: { flow: FlowDetail }) {
  const [chain, setChain] = useState(flow.chain)
  const [cleanup, setCleanup] = useState(flow.cleanup)
  const [vars, setVars] = useState(Object.entries(flow.vars))
  const cases = useQuery({ queryKey: ['cases'], queryFn: api.cases })
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })
  const names = (cases.data ?? []).map((c) => c.name)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const save = useMutation({
    mutationFn: () => api.saveFlow(flow.name, { name: flow.name, intent: flow.intent, vars: toVars(vars), chain, cleanup }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['flow', flow.name] }),
  })
  const run = useMutation({ mutationFn: () => api.runFlow(flow.name), onSuccess: ({ run_id }) => navigate(`/runs/${run_id}`) })
  const remove = useMutation({
    mutationFn: () => api.deleteFlow(flow.name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['flows'] })
      navigate('/flows')
    },
  })
  const error = save.error ?? run.error ?? remove.error

  return (
    <>
      <PageTitle title={flow.name} subline={flow.intent || null}>
        <Button variant="primary" disabled={run.isPending} onClick={() => run.mutate()}>Run</Button>
        <Button disabled={save.isPending} onClick={() => save.mutate()}>{save.isSuccess ? 'Saved' : 'Save'}</Button>
        {me.data?.role === 'admin' && (
          <Confirm label="Delete" question={`Delete the flow ${flow.name}? Its cases stay.`} onConfirm={() => remove.mutate()} />
        )}
      </PageTitle>
      {error && <p className="fail" role="alert">{error.message}</p>}
      <div className={styles.columns}>
        <CaseStack title="Chain" cases={chain} options={names} onChange={setChain} />
        <CaseStack title="Cleanup" cases={cleanup} options={names} onChange={setCleanup} />
      </div>
      <Board title="Shared vars">
        <VarRows vars={vars} onChange={setVars} />
      </Board>
      <Board title="Recent runs">
        {flow.runs.length ? <RunTable runs={flow.runs} /> : <Empty>Not run yet. Start one with Run.</Empty>}
      </Board>
    </>
  )
}
