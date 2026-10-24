import styles from './Loading.module.css'

// Rows at their real pitch with a flat bar where the text will land.
export function LoadingRows({ count = 6 }: { count?: number }) {
  return (
    <div className={styles.rows} aria-busy="true" aria-label="Loading">
      {Array.from({ length: count }, (_, i) => <div key={i} className={`tile ${styles.row}`}><span className={styles.bar} /></div>)}
    </div>
  )
}

// A block that failed to load: one sentence and Retry, in place of the block.
export function LoadError({ what, onRetry }: { what: string; onRetry: () => void }) {
  return (
    <div className={`tile ${styles.error}`} role="alert">
      <span>Couldn't load {what}.</span>
      <button type="button" className={styles.retry} onClick={onRetry}>Retry</button>
    </div>
  )
}
