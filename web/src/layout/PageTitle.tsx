import type { ReactNode } from 'react'
import styles from './PageTitle.module.css'

interface Props {
  title: string
  subline?: ReactNode
  children?: ReactNode
}

// Page heading, optional subline, and actions on the right.
export function PageTitle({ title, subline, children }: Props) {
  return (
    <header className={styles.header}>
      <div className={styles.text}>
        <h1>{title}</h1>
        {subline && <p className="muted">{subline}</p>}
      </div>
      {children && <div className={styles.actions}>{children}</div>}
    </header>
  )
}
