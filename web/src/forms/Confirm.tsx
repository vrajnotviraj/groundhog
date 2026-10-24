import { useState } from 'react'
import { Button } from './Button'
import styles from './Confirm.module.css'

interface Props {
  label: string
  question: string
  onConfirm: () => void
}

// A destructive button that asks for confirmation in place.
export function Confirm({ label, question, onConfirm }: Props) {
  const [asking, setAsking] = useState(false)
  if (!asking) return <Button variant="quiet" onClick={() => setAsking(true)}>{label}</Button>
  return (
    <span className={styles.confirm} role="group" aria-label={question}>
      <span>{question}</span>
      <Button variant="destructive" onClick={() => { setAsking(false); onConfirm() }}>{label}</Button>
      <Button variant="text" onClick={() => setAsking(false)}>Keep</Button>
    </span>
  )
}
