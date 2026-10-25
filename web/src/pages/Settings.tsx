import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { NavLink, useParams } from 'react-router'
import { api, isAdmin, meQuery, settingsHealthQuery } from '../api'
import { Board } from '../layout/Board'
import { Button } from '../forms/Button'
import { Confirm } from '../forms/Confirm'
import { Field } from '../forms/Field'
import { Figure } from '../layout/Figure'
import { LoadError, LoadingRows } from '../mascot/Loading'
import { PageTitle } from '../layout/PageTitle'
import { Select } from '../forms/Select'
import { Table, type Column } from '../table/Table'
import { Tile } from '../layout/Tile'
import { ago, count } from '../format'
import type { Check, User } from '../types'
import styles from './Settings.module.css'

const TABS = [['/settings', 'Health'], ['/settings/users', 'Users'], ['/settings/about', 'About']]
// a check named like an env var is one .env setting
const ENV_NAME = /^[A-Z0-9_]+$/

export function Settings() {
  const me = useQuery(meQuery)
  const admin = isAdmin(me.data)
  const { tab } = useParams()
  const shown = tab === 'about' || (tab === 'users' && admin) ? tab : 'health'
  return (
    <>
      <PageTitle title="Settings" />
      <nav className={styles.tabs} aria-label="Settings sections">
        {TABS.filter(([to]) => admin || to !== '/settings/users').map(([to, label]) => (
          <NavLink key={to} to={to} end className={({ isActive }) => (isActive ? styles.active : styles.tab)}>{label}</NavLink>
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
  return (
    <>
      <Board title="Checks" className={styles.checks} aside={
        <span className={styles.aside}>
          <span className="muted">{failing ? `${failing} failing` : 'all pass'}</span>
          <Button variant="text" onClick={() => health.refetch()}>Check again</Button>
        </span>}>
        <EnvTile checks={checks.filter((c) => ENV_NAME.test(c.name))} />
        {checks.filter((c) => !ENV_NAME.test(c.name)).map((check) => <CheckTile key={check.name} check={check} />)}
        <Tile className={styles.stack}>
          <span className={`marker ${login.data ? (login.data.ok ? 'pass' : 'fail') : ''}`}>{loginMark(login.data?.ok)}</span>
          <span className={styles.name}>App login</span>
          <span className="small muted">{login.data?.detail ?? <>Signs in to the app under test with the <code>.env</code> account. Takes a few seconds.</>}</span>
          <Button disabled={login.isPending} onClick={() => login.mutate()}>{login.isPending ? 'Checking' : 'Run login check'}</Button>
        </Tile>
      </Board>
      <Board title="Optional settings">
        {optional.map((o) => (
          <Tile key={o.name} className={styles.optional}>
            <code>{o.name}</code>
            <span className={styles.name}>{o.set ? 'Set' : 'Not set'}</span>
            <span className={`small muted ${styles.note}`}>{o.note}</span>
          </Tile>
        ))}
        <Tile className={styles.optional}>
          <code>MAX_WORKERS</code>
          <span className={styles.name}>{workers} at a time</span>
          <span className={`small muted ${styles.note}`}>How many runs the console runs at once; the rest wait as queued.</span>
        </Tile>
      </Board>
    </>
  )
}

function loginMark(ok?: boolean) {
  if (ok === undefined) return 'Not run'
  return ok ? 'OK' : 'Fix'
}

// The .env checks as one figure, the failing ones listed first with their hint.
function EnvTile({ checks }: { checks: Check[] }) {
  const set = checks.filter((c) => c.ok).length
  const names = [...checks].sort((a, b) => Number(a.ok) - Number(b.ok))
  return (
    <Figure label="Environment" value={`${set} of ${checks.length} set`} note={
      <span className={styles.names}>
        {names.map((c) => (
          <span key={c.name} className={c.ok ? undefined : 'fail'}>
            <code>{c.name}</code>{!c.ok && c.detail !== c.name && <> {c.detail}</>}
          </span>
        ))}
      </span>
    } />
  )
}

function CheckTile({ check }: { check: Check }) {
  return (
    <Tile className={styles.stack}>
      <span className={`marker ${check.ok ? 'pass' : 'fail'}`}>{check.ok ? 'OK' : 'Fix'}</span>
      <span className={styles.name}>{check.name}</span>
      {check.detail !== check.name && <span className={`small muted ${styles.detail}`}>{check.detail}</span>}
    </Tile>
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
    <>
      <Board title={users.data ? count(users.data.length, 'user') : 'Users'}>
        {users.isError && <LoadError what="the users" onRetry={users.refetch} />}
        {users.isPending && <LoadingRows count={2} />}
        {users.data && <Table label="Users" columns={columns} rows={users.data} rowKey={(u) => u.id} />}
      </Board>
      {remove.error && <p className="fail" role="alert">{remove.error.message}</p>}
      <AddUser onAdded={refresh} />
    </>
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
      <form className={styles.addUser} onSubmit={submit}>
        <Field label="Email"><input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Password">
          <input type="password" required minLength={8} autoComplete="new-password" value={password}
            onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Select label="Role" value={role} options={['member', 'admin']} onChange={(e) => setRole(e.target.value as User['role'])} />
        <Button variant="primary" type="submit" disabled={add.isPending}>Add user</Button>
      </form>
      {add.error && <p className="fail" role="alert">{add.error.message}</p>}
    </Board>
  )
}

function About() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health })
  const checks = useQuery(settingsHealthQuery)
  const mongo = checks.data?.checks.find((c) => c.name.toLowerCase().includes('mongo'))
  return (
    <Board className={styles.about}>
      <Tile className={styles.stack}>
        <span className="small muted">Version</span>
        <span className={styles.name}>{health.data?.version ?? '-'}</span>
      </Tile>
      <Tile className={styles.stack}>
        <span className="small muted">Database</span>
        <span className={styles.name}>{mongo?.detail ?? '-'}</span>
      </Tile>
      <Tile className={styles.stack}>
        <span className="small muted">Documentation</span>
        <span><code>README.md</code> in the repo root covers the CLI, the console and <code>./start.sh</code>.</span>
      </Tile>
    </Board>
  )
}
