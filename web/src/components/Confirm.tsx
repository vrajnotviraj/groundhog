import { useState } from 'react'
import { Button } from './Button'
import styles from './Confirm.module.css'

interface Props {
  label: string
  question: string
  onConfirm: () => void
  disabled?: boolean
}

// A destructive action that asks once, in place, before it acts.
export function Confirm({ label, question, onConfirm, disabled }: Props) {
  const [asking, setAsking] = useState(false)
  if (!asking) return <Button variant="quiet" disabled={disabled} onClick={() => setAsking(true)}>{label}</Button>
  return (
    <span className={styles.confirm} role="group" aria-label={question}>
      <span>{question}</span>
      <Button variant="destructive" onClick={() => { setAsking(false); onConfirm() }}>{label}</Button>
      <Button variant="text" onClick={() => setAsking(false)}>Keep</Button>
    </span>
  )
}
