import type { ReactNode } from 'react'
import { Mascot } from './Mascot'
import { Tile } from './Tile'
import styles from './Empty.module.css'

interface Props {
  children: ReactNode
  mascot?: boolean
}

// An empty block keeps its frame and says one sentence; the mascot only where the screen allows it.
export function Empty({ children, mascot = false }: Props) {
  return (
    <div className={mascot ? styles.withMascot : styles.empty}>
      {mascot && <Mascot />}
      <Tile className={styles.text}>
        <p>{children}</p>
      </Tile>
    </div>
  )
}
