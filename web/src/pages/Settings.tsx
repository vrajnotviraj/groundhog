import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { NavLink, useParams } from 'react-router'
import { api, isAdmin, meQuery, settingsHealthQuery } from '../api'
import { Board } from '../layout/Board'
import { Button } from '../forms/Button'
import { Confirm } from '../forms/Confirm'
import { Field } from '../forms/Field'
import { LoadError, LoadingRows } from '../mascot/Loading'
import { PageTitle } from '../layout/PageTitle'
import { Select } from '../forms/Select'
import { Table, type Column } from '../table/Table'
import { ago, count } from '../format'
import type { Check, User } from '../types'
import form from '../styles/form.module.css'
import styles from './Settings.module.css'

const TABS = [['/settings', 'Health'], ['/settings/users', 'Users'], ['/settings/about', 'About']]

export function Settings() {
  const me = useQuery(meQuery)
  const admin = isAdmin(me.data)
  const { tab } = useParams()
  const shown = tab === 'about' || (tab === 'users' && admin) ? tab : 'health'
  return (
    <>
      <PageTitle title="Settings" />
      <nav className="tabs" aria-label="Settings sections">
        {TABS.filter(([to]) => admin || to !== '/settings/users').map(([to, label]) => (
          <NavLink key={to} to={to} end className="tab">{label}</NavLink>
        ))}
      </nav>
      {shown === 'health' && <Health />}
      {shown === 'users' && <Users myEmail={me.data?.email} />}
      {shown === 'about' && <About />}
    </>
  )
}

function Health() {
  const health = useQuery(settingsHealthQuery)
  const login = useMutation({ mutationFn: api.checkLogin })
  if (health.isError) return <LoadError what="the health checks" onRetry={health.refetch} />
  if (!health.data) return <LoadingRows count={4} />
  const { checks, optional, workers } = health.data
  const failing = checks.filter((c) => !c.ok).length
  // failing checks first, so the thing to fix leads
  const sorted = [...checks].sort((a, b) => Number(a.ok) - Number(b.ok))
  return (
    <>
      <Board title="Checks" aside={
        <span className={styles.aside}>
          <span className="muted">{failing ? `${failing} failing` : 'all pass'}</span>
          <Button variant="text" onClick={() => health.refetch()}>Check again</Button>
        </span>}>
        <ul className={styles.list} aria-label="Checks">
          {sorted.map((check) => <CheckRow key={check.name} check={check} />)}
          <li className={styles.check}>
            <span className={`marker ${login.data ? (login.data.ok ? 'pass' : 'fail') : 'surface-2'}`}>{loginMark(login.data?.ok)}</span>
            <span className={styles.name}>App login</span>
            <span className={`muted ${styles.detail}`}>{login.data?.detail ?? <>Signs in to the app under test with the <code>.env</code> account. Takes a few seconds.</>}</span>
            <Button variant="secondary" disabled={login.isPending} onClick={() => login.mutate()}>{login.isPending ? 'Checking' : 'Run login check'}</Button>
          </li>
        </ul>
      </Board>
      <Board title="Optional settings">
        <ul className={styles.list}>
          {optional.map((o) => (
            <li key={o.name} className={styles.setting}>
              <code>{o.name}</code>
              <span className={styles.name}>{o.set ? 'Set' : 'Not set'}</span>
              <span className={`muted ${styles.note}`}>{o.note}</span>
            </li>
          ))}
          <li className={styles.setting}>
            <code>MAX_WORKERS</code>
            <span className={styles.name}>{workers} at a time</span>
            <span className={`muted ${styles.note}`}>How many runs the console runs at once; the rest wait as queued.</span>
          </li>
        </ul>
      </Board>
    </>
  )
}

function loginMark(ok?: boolean) {
  if (ok === undefined) return 'Not run'
  return ok ? 'OK' : 'Fix'
}

function CheckRow({ check }: { check: Check }) {
  // the API's detail often repeats the name first ("BASE_URL still the placeholder", "Jev — ...")
  const detail = check.detail.startsWith(check.name + ' ') ? check.detail.slice(check.name.length + 1).replace(/^— /, '') : check.detail
  return (
    <li className={styles.check}>
      <span className={`marker ${check.ok ? 'pass' : 'fail'}`}>{check.ok ? 'OK' : 'Fix'}</span>
      <span className={styles.name}>{check.name}</span>
      {detail !== check.name && <span className={`muted ${styles.detail}`}>{detail}</span>}
    </li>
  )
}

function Users({ myEmail }: { myEmail?: string }) {
  const users = useQuery({ queryKey: ['users'], queryFn: api.users })
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['users'] })
  const remove = useMutation({ mutationFn: api.removeUser, onSuccess: refresh })
  const columns: Column<User>[] = [
    { header: 'Email', role: 'identity', width: 'minmax(0, 2fr)', cell: (u) => u.email },
    { header: 'Role', width: '96px', role: 'key', cell: (u) => u.role },
    { header: 'Added', width: '96px', align: 'end', cell: (u) => ago(u.created_at) },
    {
      header: 'Remove', width: '72px', role: 'action',
      cell: (u) => (u.email === myEmail ? <span className="muted">you</span>
        : <Confirm label="Remove" question={`Remove ${u.email}?`} onConfirm={() => remove.mutate(u.id)} />),
    },
  ]
  return (
    <div className={styles.users}>
      <Board title={users.data ? count(users.data.length, 'user') : 'Users'}>
        {users.isError && <LoadError what="the users" onRetry={users.refetch} />}
        {users.isPending && <LoadingRows count={2} />}
        {users.data && <Table label="Users" columns={columns} rows={users.data} rowKey={(u) => u.id} />}
        {remove.error && <p className="fail" role="alert">{remove.error.message}</p>}
      </Board>
      <AddUser onAdded={refresh} />
    </div>
  )
}

function AddUser({ onAdded }: { onAdded: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<User['role']>('member')
  const add = useMutation({
    mutationFn: () => api.addUser({ email, password, role }),
    onSuccess: () => {
      setEmail('')
      setPassword('')
      onAdded()
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    add.mutate()
  }
  return (
    <Board title="Add a user">
      <form className={`tile ${form.panel} ${styles.addUser}`} onSubmit={submit}>
        <Field label="Email"><input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Password">
          <input type="password" required minLength={8} autoComplete="new-password" value={password}
            onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Select label="Role" value={role} options={['member', 'admin']} onChange={(e) => setRole(e.target.value as User['role'])} />
        <Button variant="primary" type="submit" disabled={add.isPending}>Add user</Button>
        {add.error && <p className="fail" role="alert">{add.error.message}</p>}
      </form>
    </Board>
  )
}

function About() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health })
  const checks = useQuery(settingsHealthQuery)
  const mongo = checks.data?.checks.find((c) => c.name.toLowerCase().includes('mongo'))
  return (
    <Board title="This console">
      <dl className={styles.list}>
        <div className={styles.fact}>
          <dt>Version</dt>
          <dd>{health.data?.version ?? '-'}</dd>
        </div>
        <div className={styles.fact}>
          <dt>Database</dt>
          <dd>{mongo?.detail ?? '-'}</dd>
        </div>
        <div className={styles.fact}>
          <dt>Documentation</dt>
          <dd><code>README.md</code> in the repo root covers the CLI, the console and <code>./start.sh</code>.</dd>
        </div>
      </dl>
    </Board>
  )
}
