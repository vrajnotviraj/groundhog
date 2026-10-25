import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { api } from '../api'
import { Button } from '../forms/Button'
import { Empty } from '../mascot/Empty'
import { Field } from '../forms/Field'
import { LoadError, LoadingRows } from '../mascot/Loading'
import { PageTitle } from '../layout/PageTitle'
import { RunTable } from '../run/RunTable'
import { Select } from '../forms/Select'
import { count } from '../format'
import styles from './Runs.module.css'

const PAGE = 50
const KINDS = [{ value: '', label: 'Any kind' }, 'run', 'flow', 'author', 'compose', 'crawl']
const STATUSES = [{ value: '', label: 'Any status' }, 'queued', 'running', 'passed', 'failed', 'error']

export function Runs() {
  const [params, setParams] = useSearchParams()
  const kind = params.get('kind') ?? ''
  const status = params.get('status') ?? ''
  const target = params.get('target') ?? ''
  const [limit, setLimit] = useState(PAGE)
  // each filter lives in the URL, so links can open a filtered list and Back restores it
  const filter = (name: string) => (e: { target: { value: string } }) => {
    const next = new URLSearchParams(params)
    if (e.target.value) next.set(name, e.target.value)
    else next.delete(name)
    setParams(next, { replace: true })
  }
  const filters = { limit, kind, status, target: target.trim() }
  const runs = useQuery({
    queryKey: ['runs', filters], queryFn: () => api.runs(filters), placeholderData: keepPreviousData,
    refetchInterval: 3000, // picks up runs started from the CLI
  })
  const filtered = Boolean(kind || status || target.trim())

  return (
    <>
      <PageTitle title="Runs" subline={runs.data && `${count(runs.data.length, 'run')}${filtered ? ' match' : ''}`} />
      <div className={styles.filters}>
        <Select label="Kind" value={kind} options={KINDS} onChange={filter('kind')} />
        <Select label="Status" value={status} options={STATUSES} onChange={filter('status')} />
        <Field label="Target">
          <input type="search" placeholder="Case or flow name" value={target} onChange={filter('target')} />
        </Field>
      </div>
      {runs.isError && <LoadError what="the runs" onRetry={runs.refetch} />}
      {runs.isPending && <LoadingRows />}
      {runs.data && !runs.data.length && (
        filtered ? <Empty mood="worried">No runs match these filters.</Empty> : <Empty>No runs yet. Run a case to see it here.</Empty>
      )}
      {runs.data && runs.data.length > 0 && <RunTable runs={runs.data} />}
      {runs.data?.length === limit && (
        <Button className={styles.more} onClick={() => setLimit(limit + PAGE)}>Load {PAGE} more (showing {limit})</Button>
      )}
    </>
  )
}
