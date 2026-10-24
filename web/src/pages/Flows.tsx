import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router'
import { api } from '../api'
import { Button } from '../components/Button'
import { Empty } from '../components/Empty'
import { LastRun } from '../components/LastRun'
import { LoadError, LoadingRows } from '../components/Loading'
import { PageTitle } from '../components/PageTitle'
import { Table, type Column } from '../components/Table'
import { count } from '../format'
import type { FlowCase, FlowSummary } from '../types'

const sentence = (cases: FlowCase[]) => cases.map((c) => c.case).join(', then ') || '-'

export function Flows() {
  const flows = useQuery({ queryKey: ['flows'], queryFn: api.flows })
  const navigate = useNavigate()
  const run = useMutation({ mutationFn: (name: string) => api.runFlow(name), onSuccess: ({ run_id }) => navigate(`/runs/${run_id}`) })

  const columns: Column<FlowSummary>[] = [
    { header: 'Name', role: 'identity', width: 'minmax(0, 1.5fr)', cell: (f) => <Link to={`/flows/${f.name}`}>{f.name}</Link> },
    { header: 'Chain', role: 'secondary', width: 'minmax(0, 3fr)', cell: (f) => sentence(f.chain) },
    { header: 'Cleanup', width: 'minmax(0, 1.5fr)', cell: (f) => sentence(f.cleanup) },
    { header: 'Vars', width: '64px', align: 'end', role: 'key', cell: (f) => count(Object.keys(f.vars).length, 'var') },
    {
      header: 'Last run', width: 'minmax(136px, 1.5fr)',
      cell: (f) => <LastRun run={f.last_run} />,
    },
    {
      header: 'Run', width: '40px', role: 'action',
      cell: (f) => <Button variant="text" disabled={run.isPending} onClick={() => run.mutate(f.name)}>Run</Button>,
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
