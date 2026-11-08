import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, casesQuery, settingsHealthQuery, type RunOptions } from '../api'
import { Board } from '../layout/Board'
import { Button } from '../forms/Button'
import type { Mood } from '../mascot/Groundhog'
import { LoadError, LoadingRows } from '../mascot/Loading'
import { HistoryStrip } from '../run/HistoryStrip'
import { RunForm } from '../run/RunForm'
import { RunTable } from '../run/RunTable'
import { Mascot } from '../mascot/Mascot'
import { Select } from '../forms/Select'
import { ago, count, intentVars, isToday, runTitle } from '../format'
import { isLive, useStartRun } from '../run/live'
import type { RunSummary } from '../types'
import styles from './Overview.module.css'

export function Overview() {
  // shortcut: counts cap at 500 runs a day, add a count endpoint when a day passes that
  const runs = useQuery({ queryKey: ['runs', {}], queryFn: () => api.runs({ limit: 500 }), refetchInterval: 3000 })
  const [picking, setPicking] = useState(false)
  const today = (runs.data ?? []).filter((r) => isToday(r.created_at))
  const passed = today.filter((r) => r.status === 'passed').length
  const healed = today.reduce((sum, r) => sum + (r.healed ?? 0), 0)
  const aiCalls = today.reduce((sum, r) => sum + (r.ai_calls ?? 0), 0)

  const failedRuns = today.filter((r) => r.status === 'failed' || r.status === 'error')
  const failed = failedRuns.length
  const live = today.filter((r) => isLive(r.status)).length
  let mood: Mood = 'happy'
  if (runs.isError && !runs.data) mood = 'worried'
  else if (live) mood = 'dig'
  else if (failed) mood = 'worried'
  else if (!today.length) mood = 'sleep'

  const date = new Date().toLocaleDateString('en', { weekday: 'long', day: 'numeric', month: 'long' })
  let title = 'Checking today\'s runs'
  if (runs.isError && !runs.data) title = 'Couldn\'t load today\'s runs'
  else if (runs.data) title = headline(today.length, passed, failed, live)

  // Today leads: one ink tile with the verdict, the run strip and the day's figures; the picker opens beside it.
  return (
    <>
      <div className={`${styles.hero} ${picking ? styles.picking : ''}`}>
        <Mascot mood={mood} className={styles.verdict}>
          <div className={styles.verdictText}>
            <h1 className={styles.headline}>{title}</h1>
            <p className={styles.subline}>{date}{runs.data ? `. ${todaySummary(today)}` : ''}</p>
            {today.length > 0 && (
              <HistoryStrip size="large" label="Today's runs"
                runs={[...today].reverse().map((r) => ({ id: r.id, status: r.status, flaky: r.flaky, title: runTitle(r) }))} />
            )}
            {runs.data && (
              <dl className={styles.figures}>
                <Stat label="Runs today" value={today.length} />
                <Stat label="Pass rate" value={today.length ? `${Math.round((passed / today.length) * 100)}%` : '-'} />
                <Stat label="Healed steps" value={healed} />
                <Stat label="AI calls today" value={aiCalls} />
              </dl>
            )}
            <div className={styles.actions}>
              <Button variant={picking ? 'secondary' : 'primary'} onClick={() => setPicking(!picking)}>{picking ? 'Close' : 'Run a case'}</Button>
              {failed === 1 && <Button variant="text" className={styles.failure} to={`/runs/${failedRuns[0].id}`}>Open the failed run</Button>}
              {failed > 1 && <Button variant="text" className={styles.failure} to="/runs?status=failed">Show {failed} failed</Button>}
            </div>
          </div>
        </Mascot>
        {picking && <CasePicker onClose={() => setPicking(false)} />}
      </div>
      <Board title="Latest runs" aside={runs.data?.length ? <Button variant="text" to="/runs">View all</Button> : null}>
        <LatestRuns runs={runs.data} isError={runs.isError} onRetry={runs.refetch} />
      </Board>
    </>
  )
}

// One of the day's figures, drawn on the ink tile: number first, label under it.
function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className={styles.stat}>
      <dt className={`small ${styles.statLabel}`}>{label}</dt>
      <dd className={styles.statValue}>{value}</dd>
    </div>
  )
}

// Headline for today's runs.
function headline(runs: number, passed: number, failed: number, live: number): string {
  if (!runs) return 'No runs yet today'
  if (live) return `${count(live, 'run')} replaying now`
  if (failed) return `${failed} of ${runs} failed today`
  if (passed === runs) return `All ${count(runs, 'run')} passed`
  return `${passed} of ${runs} runs passed`
}

// The line under the headline: when the last run started.
function todaySummary(today: RunSummary[]): string {
  if (!today.length) return 'The groundhog is asleep. Run a case to wake it up.'
  const last = today.reduce((a, b) => (a.created_at > b.created_at ? a : b))
  return `Last run ${ago(last.created_at)}`
}

function LatestRuns({ runs, isError, onRetry }: { runs?: RunSummary[]; isError: boolean; onRetry: () => void }) {
  if (isError) return <LoadError what="the latest runs" onRetry={onRetry} />
  if (!runs) return <LoadingRows />
  // the hero already shows the groundhog, so the second empty state is a plain sentence
  if (!runs.length) return <p className="tile">No runs yet. Run a case to see it here.</p>
  return <RunTable runs={runs.slice(0, 6)} />
}

const ALL = '*'

// Pick a saved case, or all of them, and start the run where the figures were.
function CasePicker({ onClose }: { onClose: () => void }) {
  const cases = useQuery(casesQuery)
  const health = useQuery(settingsHealthQuery)
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const start = useStartRun(({ name, options }: { name: string; options: RunOptions }) => api.runCase(name, options))
  const runAll = useMutation({
    mutationFn: ({ heal, retries }: RunOptions) =>
      api.batchRun({ cases: (cases.data ?? []).map((c) => c.name), flows: [], heal, retries }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['runs'] })
      onClose()
    },
  })
  if (cases.isError) return <LoadError what="the cases" onRetry={cases.refetch} />
  if (!cases.data) return <LoadingRows count={1} />
  const names = cases.data.map((c) => c.name)
  if (!names.length) return <p className="tile">No saved cases yet. Author one under Cases.</p>
  const chosen = name === ALL ? undefined : cases.data.find((c) => c.name === name) ?? cases.data[0]
  const options = [{ value: ALL, label: `All cases (${names.length})` }, ...names]
  const select = <Select label="Case" value={chosen?.name ?? ALL} onChange={(e) => setName(e.target.value)} options={options} />
  if (!chosen) {
    return (
      <RunForm key={ALL} title="Run a case" onClose={onClose} varNames={[]} pending={runAll.isPending}
        error={runAll.error?.message} batch={{ cases: names.length, workers: health.data?.workers }} onRun={runAll.mutate}>
        {select}
      </RunForm>
    )
  }
  return (
    <RunForm key={chosen.name} title="Run a case" onClose={onClose} varNames={intentVars(chosen.intent)} pending={start.isPending}
      error={start.error?.message} onRun={(options) => start.mutate({ name: chosen.name, options })}>
      {select}
    </RunForm>
  )
}
