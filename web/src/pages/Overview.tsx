import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { api, type RunOptions } from '../api'
import { Board } from '../components/Board'
import { Button } from '../components/Button'
import { Empty } from '../components/Empty'
import { Figure } from '../components/Figure'
import type { Mood } from '../components/Groundhog'
import { LoadError, LoadingRows } from '../components/Loading'
import { RunForm } from '../components/RunForm'
import { RunTable } from '../components/RunTable'
import { Mascot } from '../components/Mascot'
import { Select } from '../components/Select'
import { ago, count, intentVars, isToday, runTitle } from '../format'
import { isLive } from '../live'
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

  const failed = today.filter((r) => r.status === 'failed' || r.status === 'error').length
  const live = today.filter((r) => isLive(r.status)).length
  let mood: Mood = 'happy'
  if (live) mood = 'dig'
  else if (failed) mood = 'worried'
  else if (!today.length) mood = 'sleep'

  return (
    <>
      <div className={styles.hero}>
        <Mascot mood={mood} className={styles.verdict}>
          <div className={styles.verdictText}>
            <p className={styles.date}>{new Date().toLocaleDateString('en', { weekday: 'long', day: 'numeric', month: 'long' })}</p>
            <h1 className={styles.headline}>{runs.data ? headline(today.length, passed, failed, live) : 'Checking today\'s runs'}</h1>
            {runs.data && <p className={styles.subline}>{finding(today, healed)}</p>}
            {today.length > 0 && <TodayStrip runs={today} />}
            <Button variant="primary" className={styles.run} onClick={() => setPicking(!picking)}>{picking ? 'Close' : 'Run a case'}</Button>
          </div>
        </Mascot>
        <div className={styles.figures}>
          <Figure label="Runs today" value={today.length} />
          <Figure label="Pass rate" value={today.length ? `${Math.round((passed / today.length) * 100)}%` : '-'} />
          <Figure label="Healed steps" value={healed} />
          <Figure label="AI calls today" value={aiCalls} />
        </div>
      </div>
      {picking && <CasePicker />}
      <Board title="Latest runs" aside={runs.data?.length ? <Button variant="text" to="/runs">View all</Button> : null}>
        <LatestRuns runs={runs.data} isError={runs.isError} onRetry={runs.refetch} />
      </Board>
    </>
  )
}

// The day's verdict, the one sentence the screen answers.
function headline(runs: number, passed: number, failed: number, live: number): string {
  if (!runs) return 'No runs yet today'
  if (live) return `${count(live, 'run')} replaying now`
  if (failed) return `${failed} of ${runs} failed today`
  if (passed === runs) return `All ${count(runs, 'run')} passed`
  return `${passed} of ${runs} runs passed`
}

function finding(today: RunSummary[], healed: number): string {
  if (!today.length) return 'The groundhog is asleep. Run a case to wake it up.'
  const last = today.reduce((a, b) => (a.created_at > b.created_at ? a : b))
  return `${count(healed, 'healed step')} · last run ${ago(last.created_at)}`
}

// Today's runs, oldest first, one tile each in the colour of how it ended.
function TodayStrip({ runs }: { runs: RunSummary[] }) {
  return (
    <ol className={styles.strip} aria-label="Today's runs">
      {[...runs].reverse().map((r, i) => (
        <li key={r.id} style={{ animationDelay: `${i * 40}ms` }}>
          <Link to={`/runs/${r.id}`} className={`${styles.day} ${styles[r.status]}`} title={`${runTitle(r)} · ${r.status}`}
            aria-label={`${runTitle(r)}, ${r.status}`} />
        </li>
      ))}
    </ol>
  )
}

function LatestRuns({ runs, isError, onRetry }: { runs?: RunSummary[]; isError: boolean; onRetry: () => void }) {
  if (isError) return <LoadError what="the latest runs" onRetry={onRetry} />
  if (!runs) return <LoadingRows />
  if (!runs.length) return <Empty>No runs yet. Run a case to see it here.</Empty>
  return <RunTable runs={runs.slice(0, 6)} />
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
