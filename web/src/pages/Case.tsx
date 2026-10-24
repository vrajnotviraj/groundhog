import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { api, casesQuery, isAdmin, meQuery, type RunOptions } from '../api'
import { Board } from '../layout/Board'
import { Button } from '../forms/Button'
import { Confirm } from '../forms/Confirm'
import { Empty } from '../mascot/Empty'
import { LoadError, LoadingRows } from '../mascot/Loading'
import { PageTitle } from '../layout/PageTitle'
import { RunForm } from '../run/RunForm'
import { RunTable } from '../run/RunTable'
import { Table, type Column } from '../table/Table'
import { ago, checkedBy, intentVars } from '../format'
import { useStartRun } from '../run/live'
import form from '../styles/form.module.css'
import type { Assertion, Case as CaseDoc, Heal, Step } from '../types'

const STEP_COLUMNS: Column<Step>[] = [
  { header: 'Id', width: '56px', cell: (s) => <code>{s.id}</code> },
  { header: 'Action', width: '64px', role: 'key', cell: (s) => s.action },
  { header: 'Description', role: 'identity', width: 'minmax(0, 2fr)', cell: (s) => s.description },
  { header: 'Selector', width: 'minmax(0, 2fr)', cell: (s) => (s.selector ? <code>{s.selector}</code> : '-') },
  { header: 'Fallbacks', width: '72px', align: 'end', cell: (s) => s.fallback_selectors.length },
  { header: 'Expects', width: 'minmax(0, 1.5fr)', cell: (s) => (s.expects ? `${s.expects.kind.replace('_', ' ')}: ${s.expects.value}` : '-') },
]

const ASSERTION_COLUMNS: Column<Assertion>[] = [
  { header: 'Checked by', width: '120px', role: 'key', cell: (a) => checkedBy(a.mode) },
  { header: 'Assertion', role: 'identity', width: 'minmax(0, 1fr)', cell: (a) => a.assertion },
]

const HEAL_COLUMNS: Column<Heal>[] = [
  { header: 'Step', width: '56px', cell: (h) => <code>{h.step}</code> },
  { header: 'New selector', role: 'identity', width: 'minmax(0, 2fr)', cell: (h) => <code>{h.new}</code> },
  { header: 'Old selector', width: 'minmax(0, 2fr)', cell: (h) => <code>{h.old}</code> },
  { header: 'Reason', width: 'minmax(0, 2fr)', cell: (h) => h.reason },
  { header: 'When', width: '88px', align: 'end', role: 'key', cell: (h) => ago(h.at) },
]

export function Case() {
  const name = useParams().name!
  const detail = useQuery({ queryKey: ['case', name], queryFn: () => api.case(name) })
  const me = useQuery(meQuery)
  const [panel, setPanel] = useState<'run' | 'json' | null>(null)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const run = useStartRun((options: RunOptions) => api.runCase(name, options))
  const remove = useMutation({
    mutationFn: () => api.deleteCase(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: casesQuery.queryKey })
      navigate('/cases')
    },
  })

  if (detail.isError) return <><PageTitle title={name} /><LoadError what="this case" onRetry={detail.refetch} /></>
  if (!detail.data) return <><PageTitle title={name} /><LoadingRows /></>
  const { runs, updated_at, ...doc } = detail.data
  const toggle = (next: 'run' | 'json') => setPanel(panel === next ? null : next)

  return (
    <>
      <PageTitle title={name} subline={doc.intent}>
        <Button variant="primary" onClick={() => toggle('run')}>Run</Button>
        <Button onClick={() => toggle('json')}>Edit JSON</Button>
        <Button variant="text" onClick={() => download(doc)}>Download JSON</Button>
        {isAdmin(me.data) && (
          <Confirm label="Delete" question={`Delete the case ${name}? Its runs stay.`} onConfirm={() => remove.mutate()} />
        )}
      </PageTitle>
      {remove.error && <p className="fail" role="alert">{remove.error.message}</p>}
      {panel === 'run' && (
        <RunForm varNames={intentVars(doc.intent)} pending={run.isPending} error={run.error?.message} onRun={run.mutate} />
      )}
      {panel === 'json' && <JsonEditor doc={doc} onSaved={() => setPanel(null)} />}
      <CaseBlocks doc={doc} updatedAt={updated_at} />
      <Board title="Recent runs">
        {runs.length ? <RunTable runs={runs} /> : <Empty>Not run yet. Start one with Run.</Empty>}
      </Board>
    </>
  )
}

// The case's steps, assertions and heal history.
function CaseBlocks({ doc, updatedAt }: { doc: CaseDoc; updatedAt: string }) {
  return (
    <>
      <Board title="Steps" aside={<span className="muted">updated {ago(updatedAt)}</span>}>
        <Table label="Steps" columns={STEP_COLUMNS} rows={doc.steps} rowKey={(s) => s.id} />
      </Board>
      <Board title="Assertions">
        {doc.assertions.length
          ? <Table label="Assertions" columns={ASSERTION_COLUMNS} rows={doc.assertions} rowKey={(a) => a.assertion} />
          : <Empty>No assertions. The steps' expects are the only checks.</Empty>}
      </Board>
      {doc.meta.heals.length > 0 && (
        <Board title="Heal history">
          <Table label="Heal history" columns={HEAL_COLUMNS} rows={doc.meta.heals} rowKey={(h) => `${h.step}-${h.at}`} />
        </Board>
      )}
    </>
  )
}

// The case as editable JSON, with the server's validation errors below.
function JsonEditor({ doc, onSaved }: { doc: CaseDoc; onSaved: () => void }) {
  const [text, setText] = useState(JSON.stringify(doc, null, 2))
  const queryClient = useQueryClient()
  const save = useMutation({
    mutationFn: () => api.saveCase(doc.name, JSON.parse(text)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', doc.name] })
      onSaved()
    },
  })
  return (
    <div className={`tile ${form.form} ${form.panel}`}>
      <textarea aria-label="Case JSON" className={form.code} rows={20} spellCheck={false} value={text}
        onChange={(e) => setText(e.target.value)} />
      {save.error && <p className="fail" role="alert">{save.error.message}</p>}
      <Button variant="primary" disabled={save.isPending} onClick={() => save.mutate()}>Save</Button>
    </div>
  )
}

function download(doc: CaseDoc) {
  const link = document.createElement('a')
  link.href = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' }))
  link.download = `${doc.name}.json`
  link.click()
  URL.revokeObjectURL(link.href)
}
