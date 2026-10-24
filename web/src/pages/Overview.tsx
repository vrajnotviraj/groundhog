import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { api, type RunOptions } from '../api'
import { Board } from '../components/Board'
import { Button } from '../components/Button'
import { Empty } from '../components/Empty'
import { Figure } from '../components/Figure'
import { LastRun } from '../components/LastRun'
import { LoadError, LoadingRows } from '../components/Loading'
import { RunForm } from '../components/RunForm'
import { RunTable } from '../components/RunTable'
import { PageTitle } from '../components/PageTitle'
import { Select } from '../components/Select'
import { Table, type Column } from '../components/Table'
import { count, intentVars, isToday, newest } from '../format'
import type { CaseSummary, FlowSummary, RunSummary } from '../types'
import styles from './Overview.module.css'

export function Overview() {
  // shortcut: counts cap at 500 runs a day, add a count endpoint when a day passes that
  const runs = useQuery({ queryKey: ['runs', {}], queryFn: () => api.runs({ limit: 500 }), refetchInterval: 3000 })
  const [picking, setPicking] = useState(false)
  const today = (runs.data ?? []).filter((r) => isToday(r.created_at))
  const passed = today.filter((r) => r.status === 'passed').length
  const healed = today.reduce((sum, r) => sum + (r.healed ?? 0), 0)
  const aiCalls = today.reduce((sum, r) => sum + (r.ai_calls ?? 0), 0)

  return (
    <>
      <PageTitle title="Overview" subline={runs.data && finding(today.length, passed, healed)}>
        <Button variant="primary" onClick={() => setPicking(!picking)}>{picking ? 'Close' : 'Run a case'}</Button>
      </PageTitle>
      {picking && <CasePicker />}
      <div className={styles.figures}>
        <Figure label="Runs today" value={today.length} />
        <Figure label="Passed" value={passed} />
        <Figure label="Healed steps" value={healed} />
        <Figure label="AI calls today" value={aiCalls} />
      </div>
      <Board title="Latest runs" aside={runs.data?.length ? <Button variant="text" to="/runs">View all</Button> : null}>
        <LatestRuns runs={runs.data} isError={runs.isError} onRetry={runs.refetch} />
      </Board>
      <div className={styles.pair}>
        <LatestCases />
        <LatestFlows />
      </div>
    </>
  )
}

function finding(runs: number, passed: number, healed: number): string {
  if (!runs) return 'No runs today'
  return `${count(runs, 'run')} today · ${passed} passed · ${count(healed, 'healed step')}`
}

function LatestRuns({ runs, isError, onRetry }: { runs?: RunSummary[]; isError: boolean; onRetry: () => void }) {
  if (isError) return <LoadError what="the latest runs" onRetry={onRetry} />
  if (!runs) return <LoadingRows />
  if (!runs.length) return <Empty mascot>No runs yet. Run a case to see it here.</Empty>
  return <RunTable runs={runs.slice(0, 6)} />
}

const CASE_COLUMNS: Column<CaseSummary>[] = [
  { header: 'Name', role: 'identity', width: 'minmax(0, 1fr)', cell: (c) => <Link to={`/cases/${c.name}`}>{c.name}</Link> },
  { header: 'Steps', width: '64px', align: 'end', role: 'key', cell: (c) => count(c.steps, 'step') },
  { header: 'Last run', width: 'minmax(120px, auto)', cell: (c) => <LastRun run={c.last_run} /> },
]

const FLOW_COLUMNS: Column<FlowSummary>[] = [
  { header: 'Name', role: 'identity', width: 'minmax(0, 1fr)', cell: (f) => <Link to={`/flows/${f.name}`}>{f.name}</Link> },
  { header: 'Chain', width: '72px', align: 'end', role: 'key', cell: (f) => count(f.chain.length, 'case') },
  { header: 'Last run', width: 'minmax(120px, auto)', cell: (f) => <LastRun run={f.last_run} /> },
]

// The five most recently updated cases.
function LatestCases() {
  const cases = useQuery({ queryKey: ['cases'], queryFn: api.cases })
  const latest = newest(cases.data ?? [], 5)
  return (
    <Board title="Cases" aside={cases.data?.length ? <Total count={count(cases.data.length, 'case')} to="/cases" /> : null}>
      {cases.isError && <LoadError what="the cases" onRetry={cases.refetch} />}
      {cases.isPending && <LoadingRows count={3} />}
      {cases.data && !cases.data.length && <Empty>No cases yet. Author one under Cases.</Empty>}
      {latest.length > 0 && <Table label="Cases" columns={CASE_COLUMNS} rows={latest} rowKey={(c) => c.name} />}
    </Board>
  )
}

// The five most recently updated flows.
function LatestFlows() {
  const flows = useQuery({ queryKey: ['flows'], queryFn: api.flows })
  const latest = newest(flows.data ?? [], 5)
  return (
    <Board title="Flows" aside={flows.data?.length ? <Total count={count(flows.data.length, 'flow')} to="/flows" /> : null}>
      {flows.isError && <LoadError what="the flows" onRetry={flows.refetch} />}
      {flows.isPending && <LoadingRows count={3} />}
      {flows.data && !flows.data.length && <Empty>No flows yet. Chain saved cases into one.</Empty>}
      {latest.length > 0 && <Table label="Flows" columns={FLOW_COLUMNS} rows={latest} rowKey={(f) => f.name} />}
    </Board>
  )
}

function Total({ count, to }: { count: string; to: string }) {
  return (
    <span className={styles.aside}>
      <span className="muted">{count}</span>
      <Button variant="text" to={to}>View all</Button>
    </span>
  )
}

// Pick a saved case, fill its vars, start it and follow the run.
function CasePicker() {
  const cases = useQuery({ queryKey: ['cases'], queryFn: api.cases })
  const [name, setName] = useState('')
  const navigate = useNavigate()
  const start = useMutation({
    mutationFn: ({ name, options }: { name: string; options: RunOptions }) => api.runCase(name, options),
    onSuccess: ({ run_id }) => navigate(`/runs/${run_id}`),
  })
  if (cases.isError) return <LoadError what="the cases" onRetry={cases.refetch} />
  if (!cases.data) return <LoadingRows count={1} />
  const chosen = cases.data.find((c) => c.name === name) ?? cases.data[0]
  if (!chosen) return <Empty>No saved cases yet. Author one under Cases.</Empty>
  return (
    <RunForm key={chosen.name} varNames={intentVars(chosen.intent)} pending={start.isPending}
      error={start.error?.message} onRun={(options) => start.mutate({ name: chosen.name, options })}>
      <Select label="Case" value={chosen.name} onChange={(e) => setName(e.target.value)}
        options={cases.data.map((c) => c.name)} />
    </RunForm>
  )
}
