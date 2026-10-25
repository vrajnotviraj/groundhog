import { useQuery } from '@tanstack/react-query'
import { Fragment, useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router'
import { api } from '../api'
import { Board } from '../layout/Board'
import { Button } from '../forms/Button'
import { Empty } from '../mascot/Empty'
import { Field } from '../forms/Field'
import { LoadError, LoadingRows } from '../mascot/Loading'
import { PageTitle } from '../layout/PageTitle'
import { Table, type Column } from '../table/Table'
import { Tile } from '../layout/Tile'
import { ago, count } from '../format'
import { useStartRun } from '../run/live'
import form from '../styles/form.module.css'
import type { AppMap, Gap, MapPage, MapSection } from '../types'
import styles from './Map.module.css'

export const mapQuery = { queryKey: ['map'], queryFn: api.map }

// The Map tab: crawled pages by section, the cases that reach each one, and the gaps.
export function CoverageMap({ tabs }: { tabs: ReactNode }) {
  const map = useQuery(mapQuery)
  const [crawling, setCrawling] = useState(false)
  return (
    <>
      <PageTitle title="Coverage" subline={map.data && subline(map.data)}>
        <Button variant={crawling ? 'secondary' : 'primary'} aria-expanded={crawling} onClick={() => setCrawling(!crawling)}>
          {crawling ? 'Close' : 'Crawl'}
        </Button>
      </PageTitle>
      {tabs}
      {crawling && <CrawlForm />}
      {map.isError && <LoadError what="the map" onRetry={map.refetch} />}
      {map.isPending && <LoadingRows />}
      {map.data && !map.data.sections.length && <Empty>No pages mapped yet. Crawl the app to see which pages your cases reach.</Empty>}
      {map.data?.sections.map((section) => <SectionBoard key={section.name} section={section} />)}
      {map.data && map.data.gaps.length > 0 && <Gaps gaps={map.data.gaps} />}
    </>
  )
}

function subline(map: AppMap) {
  if (!map.crawled_at) return 'Not crawled yet'
  const covered = map.sections.reduce((n, s) => n + s.covered, 0)
  const total = map.sections.reduce((n, s) => n + s.total, 0)
  return `${covered} of ${count(total, 'page')} covered · crawled ${ago(map.crawled_at)}`
}

function CrawlForm() {
  const [scope, setScope] = useState('/')
  const [maxPages, setMaxPages] = useState(40)
  const [headed, setHeaded] = useState(false)
  const crawl = useStartRun(() => api.crawl({ scope, max_pages: maxPages, headed }))
  const submit = (e: FormEvent) => {
    e.preventDefault()
    crawl.mutate()
  }
  return (
    <form className={`tile ${form.form} ${form.panel}`} onSubmit={submit}>
      <div className={styles.fields}>
        <Field label="Scope" hint="Follows links under this path and clicks nothing.">
          <input required pattern={'/\\S{0,200}'} value={scope} onChange={(e) => setScope(e.target.value)} />
        </Field>
        <Field label="Max pages">
          <input type="number" required min={1} max={200} value={maxPages} onChange={(e) => setMaxPages(Number(e.target.value))} />
        </Field>
      </div>
      <label className={form.check}>
        <input type="checkbox" checked={headed} onChange={(e) => setHeaded(e.target.checked)} />Show the browser
      </label>
      <Button variant="primary" type="submit" disabled={crawl.isPending}>Start crawl</Button>
      {crawl.error && <p className="fail" role="alert">{crawl.error.message}</p>}
    </form>
  )
}

export function SectionBoard({ section }: { section: MapSection }) {
  return (
    <Board title={`${section.name} · ${section.covered} of ${section.total} covered`} className={styles.pages}>
      {section.pages.map((page) => <PageTile key={page.path} page={page} />)}
    </Board>
  )
}

function PageTile({ page }: { page: MapPage }) {
  const covered = page.cases.length > 0
  return (
    <Tile tone={covered ? 'surface' : 'surface-2'} className={styles.page}>
      <span className={styles.title}>{page.title || page.path}</span>
      <code>{page.path}</code>
      <span className="small">{count(page.controls.length, 'control')}</span>
      {covered ? (
        <span className="small">
          <span className={styles.covered}>{count(page.cases.length, 'case')}</span>{' '}
          {page.cases.map((name, i) => <Fragment key={name}>{i > 0 && ', '}<Link to={`/cases/${name}`}>{name}</Link></Fragment>)}
        </span>
      ) : <span className="small">No case visits it</span>}
    </Tile>
  )
}

const GAP_COLUMNS: Column<Gap>[] = [
  { header: 'Control', role: 'identity', width: 'minmax(0, 2fr)', cell: (g) => `${g.control.label} · ${g.control.kind}` },
  { header: 'Page', width: 'minmax(0, 2fr)', cell: (g) => <code>{g.path}</code> },
  { header: 'Why', role: 'secondary', width: 'minmax(0, 2fr)', cell: (g) => g.why },
]

function Gaps({ gaps }: { gaps: Gap[] }) {
  return (
    <Board title="Gaps" aside={<Button to="/coverage/suggestions?map=1">Suggest tests from these gaps</Button>}>
      <Table label="Gaps" columns={GAP_COLUMNS} rows={gaps} rowKey={(g) => `${g.path} ${g.control.role} ${g.control.label}`} />
    </Board>
  )
}
