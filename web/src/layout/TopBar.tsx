import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link, NavLink } from 'react-router'
import { api } from '../api'
import { Groundhog } from '../mascot/Groundhog'
import styles from './TopBar.module.css'

const LINKS = [
  ['/', 'Overview'], ['/cases', 'Cases'], ['/coverage', 'Coverage'], ['/flows', 'Flows'], ['/runs', 'Runs'],
  ['/settings', 'Settings'],
]

interface Props {
  email: string
  onSignOut: () => void
}

// The top navigation bar; on a phone the links open as a full-screen menu.
export function TopBar({ email, onSignOut }: Props) {
  const [open, setOpen] = useState(false)
  const nav = useRef<HTMLElement>(null)
  const menu = useRef<HTMLButtonElement>(null)
  const close = () => setOpen(false)
  const running = useRunsWith('running')
  const queued = useRunsWith('queued')
  const chip = [running.length && `${running.length} live`, queued.length && `${queued.length} queued`].filter(Boolean).join(' · ')

  useEffect(() => {
    if (!open) return
    nav.current?.querySelector('a')?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setOpen(false)
      menu.current?.focus()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])
  return (
    <header className={styles.top}>
      <div className={styles.bar}>
        <NavLink to="/" className={styles.wordmark} onClick={close}><Groundhog mark className={styles.mark} />groundhog</NavLink>
        {chip && (
          <Link to={running.length === 1 && !queued.length ? `/runs/${running[0].id}` : '/runs'} className={styles.live} onClick={close}>
            <Groundhog mark mood="dig" className={styles.liveHead} />{chip}
          </Link>
        )}
        <button type="button" ref={menu} className={styles.menu} aria-expanded={open} aria-controls="nav" onClick={() => setOpen(!open)}>
          {open ? 'Close' : 'Menu'}
        </button>
        <nav id="nav" ref={nav} className={`${styles.nav} ${open ? styles.open : ''}`}>
          {LINKS.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === '/'} onClick={close}
              className={({ isActive }) => `${styles.link} ${isActive ? styles.active : ''}`}>
              {label}
            </NavLink>
          ))}
          <span className={styles.user}>
            <span className={styles.email}>{email}</span>
            <button type="button" className={styles.signOut} onClick={onSignOut}>Sign out</button>
          </span>
        </nav>
      </div>
    </header>
  )
}

// Runs in one status, polled for the live chip.
function useRunsWith(status: 'running' | 'queued') {
  const runs = useQuery({ queryKey: ['runs', { status }], queryFn: () => api.runs({ status, limit: 100 }), refetchInterval: 5000 })
  return runs.data ?? []
}

