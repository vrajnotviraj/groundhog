import type { ReactNode } from 'react'
import styles from './Board.module.css'

interface Props {
  title?: string
  aside?: ReactNode
  className?: string
  children: ReactNode
}

// A section with an optional heading; the caller's class sets the grid columns.
export function Board({ title, aside, className = '', children }: Props) {
  return (
    <section className={styles.section}>
      {title && (
        <header className={styles.header}>
          <h2>{title}</h2>
          {aside}
        </header>
      )}
      <div className={`${styles.board} ${className}`}>{children}</div>
    </section>
  )
}
