import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { api, casesQuery, settingsHealthQuery } from '../api'
import { Button } from '../forms/Button'
import { Confirm } from '../forms/Confirm'
import { Empty } from '../mascot/Empty'
import { HistoryStrip } from '../run/HistoryStrip'
import { LoadError, LoadingRows } from '../mascot/Loading'
import { PageTitle } from '../layout/PageTitle'
import { StatusTile } from '../run/StatusTile'
import { Table, type Column } from '../table/Table'
import { count, duration } from '../format'
import { isLive, useStartRun } from '../run/live'
import type { CaseSummary } from '../types'
import styles from './Cases.module.css'

export function Cases() {
  const cases = useQuery(casesQuery)
  const workers = useQuery(settingsHealthQuery).data?.workers
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  // case name -> the run the last batch queued for it
  const [queued, setQueued] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState('')
  const queryClient = useQueryClient()
  const run = useStartRun((name: string) => api.runCase(name))
  const batch = useMutation({
    mutationFn: (names: string[]) => api.batchRun({ cases: names, flows: [] }),
    onSuccess: ({ run_ids }, names) => {
      setQueued(Object.fromEntries(names.map((name, i) => [name, run_ids[i]])))
      setSelected([])
      setNotice(`${count(names.length, 'run')} queued`)
      setTimeout(() => setNotice(''), 6000)
      queryClient.invalidateQueries({ queryKey: ['runs'] })
    },
  })
  const recent = useQuery({
    queryKey: ['runs', { limit: 100 }], queryFn: () => api.runs({ limit: 100 }),
    enabled: Object.keys(queued).length > 0,
    refetchInterval: (q) => (q.state.data?.some((r) => Object.values(queued).includes(r.id) && isLive(r.status)) ? 3000 : false),
  })
  const all = cases.data ?? []
  const term = search.trim().toLowerCase()
  const shown = all.filter((c) => `${c.name} ${c.intent}`.toLowerCase().includes(term))
  const allShown = shown.length > 0 && shown.every((c) => selected.includes(c.name))
  const toggle = (name: string) => setSelected(selected.includes(name) ? selected.filter((n) => n !== name) : [...selected, name])
  const statusOf = (id: string) => recent.data?.find((r) => r.id === id)?.status ?? 'queued'

  const columns: Column<CaseSummary>[] = [
    {
      header: 'Select', role: 'lead', width: '44px',
      head: (
        <span className={styles.pickAll}>
          <input type="checkbox" aria-label="Select all" checked={allShown}
            onChange={() => setSelected(allShown ? [] : shown.map((c) => c.name))} />
        </span>
      ),
      cell: (c) => (
        <label className={styles.pick}>
          <input type="checkbox" aria-label={`Select ${c.name}`} checked={selected.includes(c.name)} onChange={() => toggle(c.name)} />
        </label>
      ),
    },
    { header: 'Name', role: 'identity', width: 'minmax(0, 2fr)', cell: (c) => <Name c={c} /> },
    { header: 'Intent', role: 'secondary', width: 'minmax(0, 3fr)', cell: (c) => <Intent text={c.intent} /> },
    { header: 'Steps', width: '72px', align: 'end', role: 'key', cell: (c) => count(c.steps, 'step') },
    { header: 'Last 10', width: 'minmax(176px, 1.5fr)', cell: (c) => <Health c={c} /> },
    { header: 'Avg', width: '64px', align: 'end', cell: (c) => duration(c.health.avg_ms ?? undefined) },
    {
      header: 'Run', width: '80px', role: 'action',
      cell: (c) => (queued[c.name] && isLive(statusOf(queued[c.name]))
        ? <Link to={`/runs/${queued[c.name]}`}><StatusTile status={statusOf(queued[c.name])} /></Link>
        : <Button variant="text" disabled={run.isPending && run.variables === c.name} onClick={() => run.mutate(c.name)}>Run</Button>),
    },
  ]
  const error = run.error ?? batch.error

  return (
    <>
      <PageTitle title="Cases" subline={cases.data && (term ? `${shown.length} of ${count(all.length, 'case')}` : count(all.length, 'case'))}>
        <input type="search" className={styles.search} aria-label="Search cases" placeholder="Search name or intent"
          value={search} onChange={(e) => setSearch(e.target.value)} />
        <Button variant="text" to="/coverage/suggestions">Suggest tests</Button>
        {all.length > 0 && (
          <Confirm variant="primary" label="Run all" confirmLabel={`Run ${count(all.length, 'case')}`}
            question={`Run all ${count(all.length, 'case')}?${estimate(all, workers)}`}
            onConfirm={() => batch.mutate(all.map((c) => c.name))} />
        )}
        <Button variant="primary" to="/cases/new">New case</Button>
      </PageTitle>
      {error && <p className="fail" role="alert">{error.message}</p>}
      {cases.isError && <LoadError what="the cases" onRetry={cases.refetch} />}
      {cases.isPending && <LoadingRows />}
      {cases.data && !all.length && (
        <Empty>
          No cases yet. Describe one in English, or let Groundhog suggest some from your docs.{' '}
          <Button variant="text" to="/cases/new">New case</Button> · <Button variant="text" to="/coverage/suggestions">Suggest tests</Button>
        </Empty>
      )}
      {all.length > 0 && !shown.length && <Empty mood="worried">No case matches "{search}".</Empty>}
      {shown.length > 0 && <Table label="Cases" columns={columns} rows={shown} rowKey={(c) => c.name} />}
      {(selected.length > 0 || notice) && (
        <div className={styles.bar} role="region" aria-label="Selected cases">
          {!selected.length ? (
            <>
              <span className={styles.count} role="status">{notice}</span>
              <Button variant="text" className={styles.onInk} to="/runs">View in Runs</Button>
            </>
          ) : (
            <>
              <span className={styles.count}>{selected.length} selected</span>
              {workers && <span className={styles.note}>Runs {workers} at a time</span>}
              <Button variant="quiet" className={`${styles.onInk} ${styles.push}`} onClick={() => setSelected([])}>Clear</Button>
              <Button variant="primary" disabled={batch.isPending} onClick={() => batch.mutate(selected)}>
                Run {count(selected.length, 'case')}
              </Button>
            </>
          )}
        </div>
      )}
    </>
  )
}

// The case's link, then a sun tag for heals and for flaky runs.
function Name({ c }: { c: CaseSummary }) {
  return (
    <>
      <Link to={`/cases/${c.name}`}>{c.name}</Link>
      {c.heals > 0 && <span className={styles.tag}>{count(c.heals, 'heal')}</span>}
      {c.health.flaky > 0 && <span className={styles.tag}>{c.health.flaky} flaky</span>}
    </>
  )
}

// The intent with each {{var}} set as code; the full text shows on hover.
function Intent({ text }: { text: string }) {
  return <span title={text}>{text.split(/(\{\{\s*\w+\s*\}\})/).map((part, i) => (i % 2 ? <code key={i}>{part}</code> : part))}</span>
}

// The last 10 runs as tiles, then how many passed.
function Health({ c }: { c: CaseSummary }) {
  const { runs, passed, history } = c.health
  return (
    <span className={styles.health}>
      <HistoryStrip runs={history} slots={10} />
      <span className={runs ? styles.rate : `${styles.rate} muted`}>{runs ? `${passed}/${runs}` : '-'}</span>
    </span>
  )
}

// " 3 at a time, about 4 min." from the cases' average durations; blank until the worker count is known.
function estimate(cases: CaseSummary[], workers?: number): string {
  if (!workers) return ''
  const total = cases.reduce((sum, c) => sum + (c.health.avg_ms ?? 0), 0)
  if (!total) return ` ${workers} at a time.`
  return ` ${workers} at a time, about ${Math.max(1, Math.round(total / workers / 60_000))} min.`
}
