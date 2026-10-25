import type { ReactNode } from 'react'
import { Groundhog, type Mood } from './Groundhog'
import styles from './Groundhog.module.css'

interface Props {
  mood?: Mood
  watch?: boolean
  className?: string
  children?: ReactNode
}

// The groundhog scene on a dark tile, with children drawn over it.
export function Mascot({ mood, watch, className = '', children }: Props) {
  return (
    <div className={`tile ${styles.mascot} ${className}`}>
      {children}
      <Groundhog mood={mood} watch={watch} className={styles.scene} />
    </div>
  )
}
