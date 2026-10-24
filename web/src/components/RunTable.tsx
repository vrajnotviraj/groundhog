import { Link } from 'react-router'
import { ago, duration, runTitle } from '../format'
import type { RunSummary } from '../types'
import { StatusTile } from './StatusTile'
import { StepStrip } from './StepStrip'
import { Table, type Column } from './Table'

const COLUMNS: Column<RunSummary>[] = [
  {
    header: 'Target', role: 'identity', width: 'minmax(0, 2fr)',
    cell: (r) => <><Link to={`/runs/${r.id}`}>{runTitle(r)}</Link>{r.kind !== 'run' && <span className="muted"> · {r.kind}</span>}</>,
  },
  { header: 'Steps', width: 'minmax(0, 2fr)', cell: (r) => (r.modes?.length ? <StepStrip modes={r.modes} /> : null) },
  { header: 'Duration', width: '80px', align: 'end', role: 'key', cell: (r) => duration(r.total_ms) },
  { header: 'When', width: '88px', align: 'end', cell: (r) => ago(r.created_at) },
  { header: 'Status', width: '88px', role: 'action', cell: (r) => <StatusTile status={r.status} /> },
]

// Every list of runs: the strip, the target, how it ended and when.
export function RunTable({ runs }: { runs: RunSummary[] }) {
  return <Table label="Runs" columns={COLUMNS} rows={runs} rowKey={(r) => r.id} />
}
