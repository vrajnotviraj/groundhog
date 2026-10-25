import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api } from '../api'
import { Button } from '../forms/Button'
import { StatusTile } from '../run/StatusTile'
import { Tile } from '../layout/Tile'
import { ago } from '../format'
import { isLive, useStartRun } from '../run/live'
import type { Suggestion } from '../types'
import styles from './Suggestions.module.css'

export type RowState = 'open' | 'running' | 'failed' | 'passed' | 'dismissed'
export const ROW_ORDER: RowState[] = ['open', 'running', 'failed', 'passed', 'dismissed']

const SOURCE: Record<Suggestion['source'], string> = {
  docs: 'From the docs', map: "From the map's gaps", both: 'From the docs and the map',
}

// Open and dismissed rows as saved; an authored one by its authoring run's status.
export function rowState(s: Suggestion): RowState {
  if (s.status !== 'authored') return s.status
  if (s.run_status && isLive(s.run_status)) return 'running'
  if (s.run_status === 'failed' || s.run_status === 'error') return 'failed'
  return 'passed'
}

interface Props {
  suggestion: Suggestion
  selected: boolean
  onSelect: (checked: boolean) => void
}

// One suggestion as three tiles: select, the test idea, and what to do with it.
export function SuggestionRow({ suggestion: s, selected, onSelect }: Props) {
  const queryClient = useQueryClient()
  const author = useStartRun(() => api.authorSuggestion(s.id))
  const dismiss = useMutation({
    mutationFn: () => api.dismissSuggestion(s.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['suggestions'] }),
  })
  const state = rowState(s)
  const done = state === 'passed' || state === 'dismissed'
  const vars = Object.entries(s.vars).map(([key, value]) => `${key} = ${value}`).join(' · ')
  const run = s.run_id && <Link to={`/runs/${s.run_id}`}><StatusTile status={s.run_status ?? 'queued'} /></Link>
  const error = author.error ?? dismiss.error
  return (
    <div className={styles.row}>
      <Tile className={styles.select}>
        {state === 'open' && (
          <label className={styles.hit}>
            <input type="checkbox" aria-label={`Select ${s.name}`} checked={selected} onChange={(e) => onSelect(e.target.checked)} />
          </label>
        )}
      </Tile>
      <Tile className={done ? `${styles.body} muted` : styles.body}>
        <span className={styles.name}>{s.name}</span>
        <span className={styles.clamp}>{s.intent.split(/(\{\{\s*\w+\s*\}\})/).map((part, i) => (i % 2 ? <code key={i}>{part}</code> : part))}</span>
        <span className={`small muted ${styles.clamp}`} title={s.why}>Why: {s.why}</span>
        {vars && <code>{vars}</code>}
        <span className="small muted">{SOURCE[s.source]} · {ago(s.created_at)}</span>
      </Tile>
      <Tile className={styles.action}>
        {state === 'open' && <Button disabled={author.isPending} onClick={() => author.mutate()}>Author</Button>}
        {state === 'open' && <Button variant="quiet" disabled={dismiss.isPending} onClick={() => dismiss.mutate()}>Dismiss</Button>}
        {(state === 'running' || state === 'failed') && run}
        {state === 'failed' && <Button disabled={author.isPending} onClick={() => author.mutate()}>Try again</Button>}
        {state === 'passed' && (
          <span className={styles.authored}><span className="muted">Authored</span><Link to={`/cases/${s.case}`}>Open case</Link></span>
        )}
        {state === 'dismissed' && <Button variant="quiet" disabled={dismiss.isPending} onClick={() => dismiss.mutate()}>Restore</Button>}
        {error && <span className="small fail" role="alert">{error.message}</span>}
      </Tile>
    </div>
  )
}
