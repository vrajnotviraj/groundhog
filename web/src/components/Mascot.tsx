// copy of assets/groundhog.svg: Vite only serves files under web/
import groundhog from '../assets/groundhog.svg'
import styles from './Mascot.module.css'

// The groundhog on its ink tile, enlarged so two edges crop it.
export function Mascot({ className = '' }: { className?: string }) {
  return (
    <div className={`tile ${styles.mascot} ${className}`}>
      <img src={groundhog} alt="" />
    </div>
  )
}
