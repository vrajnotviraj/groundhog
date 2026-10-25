import { useState } from 'react'
import { Button } from './Button'
import styles from './Button.module.css'

interface Props {
  label: string
  question: string
  onConfirm: () => void
  // primary: a secondary button that confirms with a primary one, for actions that start work
  variant?: 'destructive' | 'primary'
  confirmLabel?: string
}

// A button that asks for confirmation in place; destructive unless told otherwise.
export function Confirm({ label, question, onConfirm, variant = 'destructive', confirmLabel = label }: Props) {
  const [asking, setAsking] = useState(false)
  const trigger = variant === 'primary' ? 'secondary' : 'quiet'
  if (!asking) return <Button variant={trigger} onClick={() => setAsking(true)}>{label}</Button>
  return (
    <span className={styles.confirm} role="group" aria-label={question}>
      <span>{question}</span>
      <Button variant={variant} onClick={() => { setAsking(false); onConfirm() }}>{confirmLabel}</Button>
      <Button variant="text" onClick={() => setAsking(false)}>Keep</Button>
    </span>
  )
}
