import type { HTMLAttributes } from 'react'
import styles from './Tile.module.css'

export type Tone = 'surface' | 'surface-2' | 'ground' | 'pass' | 'fail' | 'sun'

// A filled rounded block.
export function Tile({ tone = 'surface', className = '', ...rest }: HTMLAttributes<HTMLDivElement> & { tone?: Tone }) {
  return <div className={`tile ${styles[tone]} ${className}`} {...rest} />
}
