import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api } from '../api'
import { Board } from '../components/Board'
import { Button } from '../components/Button'
import { Confirm } from '../components/Confirm'
import { Field } from '../components/Field'
import { Groundhog } from '../components/Groundhog'
import { LoadError, LoadingRows } from '../components/Loading'
import { PageTitle } from '../components/PageTitle'
import { Select } from '../components/Select'
import { Table, type Column } from '../components/Table'
import { Tile } from '../components/Tile'
import { ago, count } from '../format'
import type { Check, User } from '../types'
import styles from './Settings.module.css'

type Tab = 'Health' | 'Users' | 'About'

export function Settings() {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })
  const tabs: Tab[] = me.data?.role === 'admin' ? ['Health', 'Users', 'About'] : ['Health', 'About']
  const [tab, setTab] = useState<Tab>('Health')
  return (
    <>
      <PageTitle title="Settings" />
      <nav className={styles.tabs} aria-label="Settings sections">
        {tabs.map((name) => (
          <button key={name} type="button" aria-current={tab === name ? 'page' : undefined}
            className={tab === name ? styles.active : styles.tab} onClick={() => setTab(name)}>
            {name}
          </button>
        ))}
      </nav>
      {tab === 'Health' && <Health />}
      {tab === 'Users' && <Users myEmail={me.data?.email} />}
      {tab === 'About' && <About />}
    </>
  )
}

function Health() {
  const health = useQuery({ queryKey: ['settings-health'], queryFn: api.settingsHealth, staleTime: 60_000 })
  const login = useMutation({ mutationFn: api.checkLogin })
  if (health.isError) return <LoadError what="the health checks" onRetry={health.refetch} />
  if (!health.data) return <LoadingRows count={4} />
  const failing = health.data.checks.filter((c) => !c.ok).length
  return (
    <>
      <Board title="Checks" className={styles.checks} aside={
        <span className={styles.aside}>
          <Groundhog mark mood={failing ? 'worried' : 'happy'} className={styles.head} />
          <span className="muted">{failing ? `${failing} failing` : 'all pass'}</span>
          <Button variant="text" onClick={() => health.refetch()}>Check again</Button>
        </span>}>
        {health.data.checks.map((check) => <CheckTile key={check.name} check={check} />)}
        <Tile className={styles.check}>
          <span className={`${styles.mark} ${login.data ? (login.data.ok ? styles.ok : styles.bad) : ''}`}>{loginMark(login.data?.ok)}</span>
          <span className={styles.name}>App login</span>
          <span className="small muted">{login.data?.detail ?? <>Signs in to the app under test with the <code>.env</code> account. Takes a few seconds.</>}</span>
          <Button disabled={login.isPending} onClick={() => login.mutate()}>{login.isPending ? 'Checking' : 'Run login check'}</Button>
        </Tile>
      </Board>
      <Board title="Optional settings">
        {health.data.optional.map((o) => (
          <Tile key={o.name} className={styles.optional}>
            <code>{o.name}</code>
            <span className={styles.name}>{o.set ? 'Set' : 'Not set'}</span>
            <span className={`small muted ${styles.note}`}>{o.note}</span>
          </Tile>
        ))}
      </Board>
    </>
  )
}

function loginMark(ok?: boolean) {
  if (ok === undefined) return 'Not run'
  return ok ? 'OK' : 'Fix'
}

function CheckTile({ check }: { check: Check }) {
  return (
    <Tile className={styles.check}>
      <span className={`${styles.mark} ${check.ok ? styles.ok : styles.bad}`}>{check.ok ? 'OK' : 'Fix'}</span>
      {/^[A-Z0-9_]+$/.test(check.name) ? <code>{check.name}</code> : <span className={styles.name}>{check.name}</span>}
      {check.detail !== check.name && <span className="small muted">{check.detail}</span>}
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
  const checks = useQuery({ queryKey: ['settings-health'], queryFn: api.settingsHealth, staleTime: 60_000 })
  const mongo = checks.data?.checks.find((c) => c.name.toLowerCase().includes('mongo'))
  return (
    <Board className={styles.about}>
      <Tile className={styles.check}>
        <span className="small muted">Version</span>
        <span className={styles.mark}>{health.data?.version ?? '-'}</span>
      </Tile>
      <Tile className={styles.check}>
        <span className="small muted">Database</span>
        <span className={styles.name}>{mongo?.detail ?? '-'}</span>
      </Tile>
      <Tile className={styles.check}>
        <span className="small muted">Documentation</span>
        <span><code>README.md</code> in the repo root covers the CLI, the console and <code>./start.sh</code>.</span>
      </Tile>
    </Board>
  )
}
