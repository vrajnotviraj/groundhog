import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api, casesQuery } from '../api'
import { Button } from '../forms/Button'
import { Empty } from '../mascot/Empty'
import { LastRun } from '../run/LastRun'
import { LoadError, LoadingRows } from '../mascot/Loading'
import { PageTitle } from '../layout/PageTitle'
import { Table, type Column } from '../table/Table'
import { count } from '../format'
import { useStartRun } from '../run/live'
import type { FlowCase, FlowSummary } from '../types'
import styles from './Flows.module.css'

const sentence = (cases: FlowCase[]) => cases.map((c) => c.case).join(', then ') || '-'

export function Flows() {
  const flows = useQuery({ queryKey: ['flows'], queryFn: api.flows })
  const cases = useQuery(casesQuery)
  const run = useStartRun((name: string) => api.runFlow(name))
  const stepsOf = new Map((cases.data ?? []).map((c) => [c.name, c.steps]))
  // the steps of every case the flow runs, which predicts how long it takes
  const steps = (f: FlowSummary) => [...f.chain, ...f.cleanup].reduce((sum, c) => sum + (stepsOf.get(c.case) ?? 0), 0)

  const columns: Column<FlowSummary>[] = [
    {
      // the chain is what a flow is, so it reads under the name instead of in its own column
      header: 'Flow', role: 'identity', width: 'minmax(0, 2fr)',
      cell: (f) => (
        <>
          <Link to={`/flows/${f.name}`}>{f.name}</Link>
          <span className={styles.chain}>
            {sentence(f.chain)}{f.cleanup.length > 0 && <>; cleanup {sentence(f.cleanup)}</>}
          </span>
        </>
      ),
    },
    { header: 'Steps', width: '88px', align: 'end', role: 'key', cell: (f) => (cases.data ? count(steps(f), 'step') : '-') },
    {
      header: 'Last run', width: 'minmax(136px, 316px)',
      cell: (f) => <LastRun run={f.last_run} />,
    },
    {
      header: 'Run', width: '48px', role: 'action',
      cell: (f) => <Button variant="text" disabled={run.isPending && run.variables === f.name} onClick={() => run.mutate(f.name)}>Run</Button>,
    },
  ]

  return (
    <>
      <PageTitle title="Flows" subline={flows.data && count(flows.data.length, 'flow')}>
        <Button variant="primary" to="/flows/new">New flow</Button>
      </PageTitle>
      {run.error && <p className="fail" role="alert">{run.error.message}</p>}
      {flows.isError && <LoadError what="the flows" onRetry={flows.refetch} />}
      {flows.isPending && <LoadingRows />}
      {flows.data && !flows.data.length && <Empty>No flows yet. Chain saved cases into one.</Empty>}
      {flows.data && flows.data.length > 0 && <Table label="Flows" columns={columns} rows={flows.data} rowKey={(f) => f.name} />}
    </>
  )
}
