import type { ReactNode } from 'react'
import styles from './Field.module.css'

interface Props {
  label: string
  hint?: ReactNode
  className?: string
  children: ReactNode
}

// A labelled control: the label above, a hint below.
export function Field({ label, hint, className = '', children }: Props) {
  return (
    <label className={`${styles.field} ${className}`}>
      <span className="small muted">{label}</span>
      {children}
      {hint && <span className="small muted">{hint}</span>}
    </label>
  )
}
