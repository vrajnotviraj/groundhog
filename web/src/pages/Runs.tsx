import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import { Button } from '../components/Button'
import { Empty } from '../components/Empty'
import { Field } from '../components/Field'
import { LoadError, LoadingRows } from '../components/Loading'
import { PageTitle } from '../components/PageTitle'
import { RunTable } from '../components/RunTable'
import { Select } from '../components/Select'
import { count } from '../format'
import styles from './Runs.module.css'

const PAGE = 50
const KINDS = [{ value: '', label: 'Any kind' }, 'run', 'flow', 'author', 'compose']
const STATUSES = [{ value: '', label: 'Any status' }, 'queued', 'running', 'passed', 'failed', 'error']

export function Runs() {
  const [kind, setKind] = useState('')
  const [status, setStatus] = useState('')
  const [target, setTarget] = useState('')
  const [limit, setLimit] = useState(PAGE)
  const filters = { limit, kind, status, target: target.trim() }
  const runs = useQuery({
    queryKey: ['runs', filters], queryFn: () => api.runs(filters), placeholderData: keepPreviousData,
    refetchInterval: 3000, // runs started from a terminal appear without a reload
  })
  const filtered = Boolean(kind || status || target.trim())

  return (
    <>
      <PageTitle title="Runs" subline={runs.data && `${count(runs.data.length, 'run')}${filtered ? ' match' : ''}`} />
      <div className={styles.filters}>
        <Select label="Kind" value={kind} options={KINDS} onChange={(e) => setKind(e.target.value)} />
        <Select label="Status" value={status} options={STATUSES} onChange={(e) => setStatus(e.target.value)} />
        <Field label="Target">
          <input type="search" placeholder="Case or flow name" value={target} onChange={(e) => setTarget(e.target.value)} />
        </Field>
      </div>
      {runs.isError && <LoadError what="the runs" onRetry={runs.refetch} />}
      {runs.isPending && <LoadingRows />}
      {runs.data && !runs.data.length && (
        filtered ? <Empty>No runs match these filters.</Empty> : <Empty mascot>No runs yet. Run a case to see it here.</Empty>
      )}
      {runs.data && runs.data.length > 0 && <RunTable runs={runs.data} />}
      {runs.data?.length === limit && (
        <Button className={styles.more} onClick={() => setLimit(limit + PAGE)}>Load {PAGE} more</Button>
      )}
    </>
  )
}
