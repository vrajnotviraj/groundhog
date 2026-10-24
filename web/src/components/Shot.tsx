import { api } from '../api'
import { Tile } from './Tile'
import styles from './Shot.module.css'

// The screenshot taken after a step, or a sentence when there is none yet.
export function Shot({ runId, seq }: { runId: string; seq?: number }) {
  return (
    <Tile className={styles.shot}>
      {seq === undefined
        ? <p className="muted">No screenshot yet.</p>
        : <img src={api.shotUrl(runId, seq)} alt={`Page after event ${seq}`} />}
    </Tile>
  )
}
