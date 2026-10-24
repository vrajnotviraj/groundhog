import type { ReactNode } from 'react'
import { Groundhog, type Mood } from './Groundhog'
import styles from './Mascot.module.css'

interface Props {
  mood?: Mood
  watch?: boolean
  className?: string
  children?: ReactNode
}

// The groundhog in its burrow on an ink tile, sitting on the tile's bottom edge; children sit above it.
export function Mascot({ mood, watch, className = '', children }: Props) {
  return (
    <div className={`tile ${styles.mascot} ${className}`}>
      {children}
      <Groundhog mood={mood} watch={watch} className={styles.groundhog} />
    </div>
  )
}
