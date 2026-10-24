import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { api, casesQuery } from '../api'
import { Button } from '../forms/Button'
import { Empty } from '../mascot/Empty'
import { Field } from '../forms/Field'
import { LastRun } from '../run/LastRun'
import { LoadError, LoadingRows } from '../mascot/Loading'
import { PageTitle } from '../layout/PageTitle'
import { Table, type Column } from '../table/Table'
import { count } from '../format'
import { useStartRun } from '../run/live'
import type { CaseSummary } from '../types'
import styles from './Cases.module.css'

export function Cases() {
  const cases = useQuery(casesQuery)
  const [search, setSearch] = useState('')
  const run = useStartRun((name: string) => api.runCase(name))
  const term = search.trim().toLowerCase()
  const shown = (cases.data ?? []).filter((c) => `${c.name} ${c.intent}`.toLowerCase().includes(term))

  const columns: Column<CaseSummary>[] = [
    {
      header: 'Name', role: 'identity', width: 'minmax(0, 2fr)',
      cell: (c) => <><Link to={`/cases/${c.name}`}>{c.name}</Link>{c.heals > 0 && <span className={styles.heal}>{count(c.heals, 'heal')}</span>}</>,
    },
    { header: 'Intent', role: 'secondary', width: 'minmax(0, 3fr)', cell: (c) => c.intent },
    { header: 'Steps', width: '72px', align: 'end', role: 'key', cell: (c) => count(c.steps, 'step') },
    { header: 'Last run', width: 'minmax(136px, 1.5fr)', cell: (c) => <LastRun run={c.last_run} /> },
    {
      header: 'Run', width: '40px', role: 'action',
      cell: (c) => <Button variant="text" disabled={run.isPending} onClick={() => run.mutate(c.name)}>Run</Button>,
    },
  ]

  return (
    <>
      <PageTitle title="Cases" subline={cases.data && count(cases.data.length, 'case')}>
        <Button variant="primary" to="/cases/new">New case</Button>
      </PageTitle>
      <Field label="Search" className={styles.search}>
        <input type="search" placeholder="Name or intent" value={search} onChange={(e) => setSearch(e.target.value)} />
      </Field>
      {run.error && <p className="fail" role="alert">{run.error.message}</p>}
      {cases.isError && <LoadError what="the cases" onRetry={cases.refetch} />}
      {cases.isPending && <LoadingRows />}
      {cases.data && !cases.data.length && <Empty>No cases yet. Describe one in English and Jev will author it.</Empty>}
      {cases.data && cases.data.length > 0 && !shown.length && <Empty mood="worried">No case matches "{search}".</Empty>}
      {shown.length > 0 && <Table label="Cases" columns={columns} rows={shown} rowKey={(c) => c.name} />}
    </>
  )
}
