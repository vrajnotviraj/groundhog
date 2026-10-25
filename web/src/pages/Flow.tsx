import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { api, casesQuery, isAdmin, meQuery } from '../api'
import { Board } from '../layout/Board'
import { Button } from '../forms/Button'
import { CaseStack } from '../forms/CaseStack'
import { Confirm } from '../forms/Confirm'
import { Empty } from '../mascot/Empty'
import { LoadError, LoadingRows } from '../mascot/Loading'
import { PageTitle } from '../layout/PageTitle'
import { useStartRun } from '../run/live'
import { RunTable } from '../run/RunTable'
import { toVars, VarRows } from '../forms/VarRows'
import type { FlowDetail } from '../types'

export function Flow() {
  const name = useParams().name!
  const detail = useQuery({ queryKey: ['flow', name], queryFn: () => api.flow(name) })
  if (detail.isError) return <><PageTitle title={name} /><LoadError what="this flow" onRetry={detail.refetch} /></>
  if (!detail.data) return <><PageTitle title={name} /><LoadingRows /></>
  return <Builder key={detail.data.name} flow={detail.data} />
}

// Edits the flow's chain, cleanup and shared vars and saves them together.
function Builder({ flow }: { flow: FlowDetail }) {
  const [chain, setChain] = useState(flow.chain)
  const [cleanup, setCleanup] = useState(flow.cleanup)
  const [vars, setVars] = useState(Object.entries(flow.vars))
  const cases = useQuery(casesQuery)
  const me = useQuery(meQuery)
  const names = (cases.data ?? []).map((c) => c.name)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [dirty, setDirty] = useState(false)
  const store = () => api.saveFlow(flow.name, { name: flow.name, intent: flow.intent, vars: toVars(vars), chain, cleanup })
  const save = useMutation({
    mutationFn: store,
    onSuccess: () => {
      setDirty(false)
      queryClient.invalidateQueries({ queryKey: ['flow', flow.name] })
    },
  })
  // Run starts the saved flow, so unsaved edits are saved first.
  const run = useStartRun(async () => {
    if (dirty) await store()
    return api.runFlow(flow.name)
  })
  const remove = useMutation({
    mutationFn: () => api.deleteFlow(flow.name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['flows'] })
      navigate('/flows')
    },
  })
  const error = save.error ?? run.error ?? remove.error
  // any edit after a save turns the button back from Saved to Save changes
  const edited = <T,>(set: (value: T) => void) => (value: T) => { save.reset(); setDirty(true); set(value) }

  return (
    <>
      <PageTitle title={flow.name} subline={flow.intent || null}>
        <Button variant="primary" disabled={run.isPending} onClick={() => run.mutate()}>Run</Button>
        <Button disabled={save.isPending} onClick={() => save.mutate()}>{saveLabel(dirty, save.isSuccess)}</Button>
        {isAdmin(me.data) && (
          <Confirm label="Delete" question={`Delete the flow ${flow.name}? Its cases stay.`} onConfirm={() => remove.mutate()} />
        )}
      </PageTitle>
      {error && <p className="fail" role="alert">{error.message}</p>}
      <div className="split">
        <CaseStack title="Chain" cases={chain} options={names} onChange={edited(setChain)} />
        <CaseStack title="Cleanup" cases={cleanup} options={names} onChange={edited(setCleanup)} />
      </div>
      <Board title="Shared vars">
        <VarRows vars={vars} onChange={edited(setVars)} />
      </Board>
      <Board title="Recent runs">
        {flow.runs.length ? <RunTable runs={flow.runs} /> : <Empty>Not run yet. Start one with Run.</Empty>}
      </Board>
    </>
  )
}

function saveLabel(dirty: boolean, saved: boolean): string {
  if (dirty) return 'Save changes'
  return saved ? 'Saved' : 'Save'
}
