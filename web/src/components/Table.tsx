import type { CSSProperties, ReactNode } from 'react'
import styles from './Table.module.css'

export interface Column<T> {
  header: string
  cell: (row: T) => ReactNode
  width?: string
  align?: 'end'
  // identity and key share line 1 on the phone; the rest move to line 2.
  // secondary is a rest column that moves under the identity between 640 and 1100px.
  role?: 'identity' | 'key' | 'action' | 'secondary'
}

interface Props<T> {
  label: string
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
}

// Rows as tiles on a 48px pitch; below 640px each row folds into two lines.
export function Table<T>({ label, columns, rows, rowKey }: Props<T>) {
  const widths = (shown: Column<T>[]) => shown.map((c) => c.width ?? 'minmax(0, 1fr)').join(' ')
  const template = {
    '--columns': widths(columns),
    '--columns-tablet': widths(columns.filter((c) => c.role !== 'secondary')),
  } as CSSProperties
  const secondary = columns.find((c) => c.role === 'secondary')
  const roleClass = (c: Column<T>) => (c.role === 'secondary' ? `${styles.rest} ${styles.secondary}` : styles[c.role ?? 'rest'])
  const cellClass = (c: Column<T>) => `${roleClass(c)} ${c.align === 'end' ? styles.end : ''}`
  return (
    <div role="table" aria-label={label} className={styles.table} style={template}>
      <div role="row" className={styles.header}>
        {columns.map((c) => <span key={c.header} role="columnheader" className={cellClass(c)}>{c.header}</span>)}
      </div>
      {rows.map((row) => (
        <div key={rowKey(row)} role="row" className={styles.row}>
          {columns.map((c) => (
            <span key={c.header} role="cell" className={cellClass(c)}>
              {c.cell(row)}
              {c.role === 'identity' && secondary && <span className={styles.second}>{secondary.cell(row)}</span>}
            </span>
          ))}
          <span className={styles.break} />
        </div>
      ))}
    </div>
  )
}
