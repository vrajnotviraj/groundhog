import type { ReactNode } from 'react'
import { Groundhog, type Mood } from './Groundhog'
import styles from './Empty.module.css'

interface Props {
  children: ReactNode
  mood?: Mood
}

// An empty block keeps its frame: the groundhog's head and one sentence.
export function Empty({ children, mood = 'sleep' }: Props) {
  return (
    <div className={`tile ${styles.empty}`}>
      <Groundhog mark mood={mood} className={styles.head} />
      <p>{children}</p>
    </div>
  )
}
