import { NavLink, useLocation } from 'react-router'
import { CoverageMap } from '../coverage/Map'
import { Suggestions } from '../coverage/Suggestions'
import styles from './Settings.module.css'

const TABS = [['/coverage', 'Map'], ['/coverage/suggestions', 'Suggestions']]

export function Coverage() {
  const onSuggestions = useLocation().pathname.startsWith('/coverage/suggestions')
  const tabs = (
    <nav className={styles.tabs} aria-label="Coverage sections">
      {TABS.map(([to, label]) => (
        <NavLink key={to} to={to} end className={({ isActive }) => (isActive ? styles.active : styles.tab)}>
          {label}
        </NavLink>
      ))}
    </nav>
  )
  return onSuggestions ? <Suggestions tabs={tabs} /> : <CoverageMap tabs={tabs} />
}
