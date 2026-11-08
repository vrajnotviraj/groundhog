import { NavLink, useLocation } from 'react-router'
import { CoverageMap } from '../coverage/Map'
import { Suggestions } from '../coverage/Suggestions'

const TABS = [['/coverage', 'Map'], ['/coverage/suggestions', 'Suggestions']]

export function Coverage() {
  const onSuggestions = useLocation().pathname.startsWith('/coverage/suggestions')
  const tabs = (
    <nav className="tabs" aria-label="Coverage sections">
      {TABS.map(([to, label]) => (
        <NavLink key={to} to={to} end className="tab">
          {label}
        </NavLink>
      ))}
    </nav>
  )
  return onSuggestions ? <Suggestions tabs={tabs} /> : <CoverageMap tabs={tabs} />
}
