import type { ReactNode } from 'react'
import { Groundhog, type Mood } from './Groundhog'
import styles from './Groundhog.module.css'

interface Props {
  children: ReactNode
  mood?: Mood
}

// Empty state: the groundhog's head on an ink tile, and one sentence beside it.
export function Empty({ children, mood = 'sleep' }: Props) {
  return (
    <div className={styles.empty}>
      <div className={`tile ${styles.headTile}`}><Groundhog mark mood={mood} className={styles.head} /></div>
      <div className={`tile ${styles.say}`}><p>{children}</p></div>
    </div>
  )
}
