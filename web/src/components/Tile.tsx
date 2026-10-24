import type { HTMLAttributes } from 'react'
import styles from './Tile.module.css'

export type Tone = 'surface' | 'surface-2' | 'muted' | 'ground' | 'pass' | 'fail'

// One filled tile holding one thing.
export function Tile({ tone = 'surface', className = '', ...rest }: HTMLAttributes<HTMLDivElement> & { tone?: Tone }) {
  return <div className={`tile ${styles[tone]} ${className}`} {...rest} />
}
