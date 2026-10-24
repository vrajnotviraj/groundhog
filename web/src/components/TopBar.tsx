import { useEffect, useRef, useState } from 'react'
import { NavLink } from 'react-router'
import styles from './TopBar.module.css'

const LINKS = [['/', 'Overview'], ['/cases', 'Cases'], ['/flows', 'Flows'], ['/runs', 'Runs'], ['/settings', 'Settings']]

interface Props {
  email: string
  onSignOut: () => void
}

// The wordmark, the five screens and the signed-in user; on a phone the links fold into a sheet.
export function TopBar({ email, onSignOut }: Props) {
  const [open, setOpen] = useState(false)
  const nav = useRef<HTMLElement>(null)
  const menu = useRef<HTMLButtonElement>(null)
  const close = () => setOpen(false)

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
    <header className={styles.bar}>
      <NavLink to="/" className={styles.wordmark} onClick={close}>groundhog</NavLink>
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
    </header>
  )
}
