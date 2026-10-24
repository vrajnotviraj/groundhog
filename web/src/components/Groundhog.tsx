import { useEffect, useId, useRef } from 'react'
import styles from './Groundhog.module.css'

export type Mood = 'happy' | 'worried' | 'dig' | 'sleep' | 'shy'

interface Props {
  mood?: Mood
  // pupils follow the pointer
  watch?: boolean
  // the head alone, still: the wordmark, empty states, errors
  mark?: boolean
  className?: string
}

// Moods are cut into the eye whites by lids in the mask colour; sleep and shy close the eyes instead.
const LIDS: Record<Mood, [string, string] | null> = {
  happy: ['M84 140Q103 120 122 140Z', 'M118 140Q137 120 156 140Z'],
  worried: ['M84 96H122V104L84 118Z', 'M118 96H156V118L118 104Z'],
  dig: ['M84 96H122V116L84 104Z', 'M118 96H156V104L118 116Z'],
  sleep: null,
  shy: null,
}
const SINK: Record<Mood, number> = { happy: 0, worried: 8, dig: 0, sleep: 16, shy: 0 }
const FUR = '#E0873A'
const MASK = '#F4B877'
const INK = '#1B2533'

// The groundhog peeking out of its burrow in front of the sunrise.
export function Groundhog({ mood = 'happy', watch = false, mark = false, className = '' }: Props) {
  const svg = useRef<SVGSVGElement>(null)
  const id = useId().replace(/:/g, '')

  useEffect(() => {
    if (!watch) return
    const onMove = (e: PointerEvent) => {
      const box = svg.current?.getBoundingClientRect()
      if (!box) return
      const dx = e.clientX - (box.left + box.width / 2)
      const dy = e.clientY - (box.top + box.height * 0.55)
      const d = Math.hypot(dx, dy) || 1
      svg.current!.style.setProperty('--look-x', `${(dx / d) * 3}px`)
      svg.current!.style.setProperty('--look-y', `${(dy / d) * 3}px`)
    }
    window.addEventListener('pointermove', onMove)
    return () => window.removeEventListener('pointermove', onMove)
  }, [watch])

  const shown = mood
  const lids = LIDS[shown]
  const look = shown === 'dig' ? 0 : shown === 'worried' ? -2 : 2
  const grin = shown === 'happy' || shown === 'dig' || shown === 'shy'

  const head = (
    <>
      <circle cx="76" cy="84" r="15" fill={FUR} /><circle cx="164" cy="84" r="15" fill={FUR} />
      <circle cx="78" cy="86" r="7.5" fill="#A9531C" /><circle cx="162" cy="86" r="7.5" fill="#A9531C" />
      <path d="M108 74C104 58 118 52 124 61C127 52 140 54 137 70Z" fill={FUR} />
      <path d="M62 240V124C62 90 88 68 120 68C152 68 178 90 178 124V240Z" fill={FUR} />
      <path d="M148 78C164 90 172 106 172 124V240H178V124C178 102 166 86 148 78Z" fill="#C46D26" />
      <path d="M78 128C78 104 94 94 108 99C113 96 127 96 132 99C146 94 162 104 162 128C162 154 144 166 120 166C96 166 78 154 78 128Z" fill={MASK} />
      {lids && (
        <g className={styles.eyes}>
          <ellipse cx="103" cy="118" rx="15" ry="17" fill="#FFF" /><ellipse cx="137" cy="118" rx="15" ry="17" fill="#FFF" />
          <g className={styles.pupil}>
            <ellipse cx={105 + look} cy="121" rx="8" ry="9.5" fill={INK} /><ellipse cx={135 + look} cy="121" rx="8" ry="9.5" fill={INK} />
            <circle cx={108 + look} cy="116.5" r="3" fill="#FFF" /><circle cx={138 + look} cy="116.5" r="3" fill="#FFF" />
          </g>
          <path d={lids[0]} fill={MASK} clipPath={`url(#${id}l)`} />
          <path d={lids[1]} fill={MASK} clipPath={`url(#${id}r)`} />
        </g>
      )}
      {shown === 'sleep' && (
        <g stroke={INK} strokeWidth="3.6" strokeLinecap="round" fill="none"><path d="M91 121q12 9 24 0" /><path d="M125 121q12 9 24 0" /></g>
      )}
      {shown === 'shy' && (
        <g stroke={INK} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" fill="none"><path d="M95 110l14 8l-14 8" /><path d="M145 110l-14 8l14 8" /></g>
      )}
      <path d="M112 139Q120 134 128 139Q125 147 120 148Q115 147 112 139Z" fill="#3A1E10" />
      <ellipse cx="117" cy="138.5" rx="2.4" ry="1.3" fill="#FFF" opacity="0.65" />
      {grin ? (
        <g>
          <path d="M108 150Q120 168 132 150Z" fill="#5A1E1E" />
          <ellipse cx="120" cy="160" rx="5" ry="3" fill="#EF8A8F" />
          <rect x="114" y="150" width="6" height="7.5" rx="1.8" fill="#FFF" /><rect x="120" y="150" width="6" height="7.5" rx="1.8" fill="#FFF" />
        </g>
      ) : (
        <g>
          <path d="M113 156q7-4 14 0" fill="none" stroke="#3A1E10" strokeWidth="3" strokeLinecap="round" />
          <rect x="114.5" y="149" width="5.5" height="6.5" rx="1.6" fill="#FFF" /><rect x="120" y="149" width="5.5" height="6.5" rx="1.6" fill="#FFF" />
        </g>
      )}
    </>
  )
  const defs = (
    <defs>
      <clipPath id={`${id}l`}><ellipse cx="103" cy="118" rx="15" ry="17" /></clipPath>
      <clipPath id={`${id}r`}><ellipse cx="137" cy="118" rx="15" ry="17" /></clipPath>
      <clipPath id={`${id}h`}><rect x="-200" y="-200" width="640" height="374" /><ellipse cx="120" cy="174" rx="72" ry="11" /></clipPath>
    </defs>
  )

  if (mark) {
    return <svg viewBox="58 46 124 118" className={className} aria-hidden="true">{defs}{head}</svg>
  }
  return (
    <svg ref={svg} viewBox="0 0 240 200" className={`${styles.groundhog} ${styles[shown]} ${className}`} aria-hidden="true">
      {defs}
      <circle className={styles.sun} cx="120" cy="112" r="70" fill="var(--gh-sun)" />
      <path d="M-200 184C-40 174 40 158 120 158C200 158 280 174 440 184V400H-200Z" fill="#61524A" />
      <ellipse cx="120" cy="174" rx="86" ry="15" fill="#4E423B" />
      <ellipse cx="120" cy="174" rx="72" ry="11" fill="#140C08" />
      <g clipPath={`url(#${id}h)`}>
        <g transform={`translate(0 ${SINK[shown]})`}>
          <g className={styles.body}>{head}</g>
        </g>
      </g>
      {shown === 'dig' && (
        <g className={styles.dirt} fill="#8A7A6C">
          <circle cx="44" cy="160" r="5" /><rect x="56" y="142" width="7" height="5" rx="2" /><circle cx="196" cy="156" r="4.5" /><circle cx="184" cy="140" r="3" />
        </g>
      )}
      {shown === 'sleep' && (
        <g className={styles.zzz} fill="#EFEBE4" fontFamily="var(--gh-font)" fontWeight="700">
          <text x="166" y="104" fontSize="20">z</text><text x="182" y="86" fontSize="15">z</text>
        </g>
      )}
    </svg>
  )
}
