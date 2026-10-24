import type { ButtonHTMLAttributes } from 'react'
import { Link } from 'react-router'
import styles from './Button.module.css'

type Variant = 'primary' | 'secondary' | 'text' | 'quiet' | 'destructive'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  to?: string
}

// A button, or a link styled as one when `to` is set.
export function Button({ variant = 'secondary', to, className = '', children, ...rest }: Props) {
  const classes = `${styles.button} ${styles[variant]} ${className}`
  if (to) return <Link to={to} className={classes}>{children}</Link>
  return <button type="button" className={classes} {...rest}>{children}</button>
}
