import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { api } from '../api'
import { Board } from '../layout/Board'
import { Button } from '../forms/Button'
import { Empty } from '../mascot/Empty'
import { Groundhog } from '../mascot/Groundhog'
import { LoadError } from '../mascot/Loading'
import { PageTitle } from '../layout/PageTitle'
import { Tile } from '../layout/Tile'
import { SuggestForm } from './SuggestForm'
import { ROW_ORDER, rowState, SuggestionRow } from './SuggestionRow'
import type { Suggestion } from '../types'
import styles from './Suggestions.module.css'

const byState = (a: Suggestion, b: Suggestion) => ROW_ORDER.indexOf(rowState(a)) - ROW_ORDER.indexOf(rowState(b))

// The Suggestions tab: ask for test ideas, then author or dismiss them.
export function Suggestions({ tabs }: { tabs: ReactNode }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const list = useQuery({
    queryKey: ['suggestions'],
    queryFn: api.suggestions,
    refetchInterval: (query) => (query.state.data?.some((s) => rowState(s) === 'running') ? 3000 : false),
  })
  const [selected, setSelected] = useState<string[]>([])
  const [showDismissed, setShowDismissed] = useState(false)
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['suggestions'] })
  const suggest = useMutation({ mutationFn: api.suggest, onSuccess: refresh })
  const rows = [...(list.data ?? [])].sort(byState)
  const open = rows.filter((s) => s.status === 'open')
  const dismissed = rows.filter((s) => s.status === 'dismissed')
  const shown = showDismissed ? rows : rows.filter((s) => s.status !== 'dismissed')
  const picked = selected.filter((id) => open.some((s) => s.id === id))
  const authorSelected = useMutation({
    mutationFn: () => Promise.all(picked.map((id) => api.authorSuggestion(id))),
    onSuccess: () => navigate('/runs'),
    // some runs may have started before one failed
    onError: refresh,
  })
  const select = (id: string, checked: boolean) => setSelected(checked ? [...picked, id] : picked.filter((p) => p !== id))

  const selection = open.length > 0 && (
    <span className={styles.selection}>
      <Button variant="text" onClick={() => setSelected(open.map((s) => s.id))}>Select all open</Button>
      <span className="muted">{picked.length} selected</span>
      <Button variant="primary" disabled={!picked.length || authorSelected.isPending} onClick={() => authorSelected.mutate()}>
        Author selected
      </Button>
    </span>
  )
  return (
    <>
      <PageTitle title="Coverage" subline="Test ideas from your docs, your saved cases and the map's gaps. Nothing runs until you author one." />
      {tabs}
      <div className={styles.columns}>
        <SuggestForm primary={!open.length} pending={suggest.isPending} error={suggest.error} onSuggest={suggest.mutate} />
        <Board title="Suggestions" aside={selection}>
          {suggest.isPending && (
            <p role="status" className={styles.pending}>
              <Groundhog mark mood="dig" className={styles.dig} />
              Reading the docs and your saved cases. This takes 10 to 40 seconds.
            </p>
          )}
          {authorSelected.error && <p className="fail" role="alert">{authorSelected.error.message}</p>}
          {list.isError && <LoadError what="the suggestions" onRetry={list.refetch} />}
          {(list.isPending || suggest.isPending) && <PlaceholderRows />}
          {list.data && !list.data.length && !suggest.isPending && (
            <Empty>No suggestions yet. Add a docs page, paste some text or use the map's gaps.</Empty>
          )}
          {shown.map((s) => <SuggestionRow key={s.id} suggestion={s} selected={picked.includes(s.id)} onSelect={(on) => select(s.id, on)} />)}
          {dismissed.length > 0 && (
            <Button variant="quiet" className={styles.toggle} onClick={() => setShowDismissed(!showDismissed)}>
              {showDismissed ? 'Hide dismissed' : `Show ${dismissed.length} dismissed`}
            </Button>
          )}
        </Board>
      </div>
    </>
  )
}

// Six empty rows at the real row size while suggestions load.
function PlaceholderRows() {
  return (
    <div className={styles.placeholders} aria-busy="true" aria-label="Loading suggestions">
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className={styles.row}>
          <Tile className={styles.select} />
          <Tile className={styles.body}><span className={styles.bar} /><span className={styles.bar} /></Tile>
          <Tile className={styles.action} />
        </div>
      ))}
    </div>
  )
}
