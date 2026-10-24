import type { SelectHTMLAttributes } from 'react'
import { Field } from './Field'

interface Props extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string
  options: (string | { value: string; label: string })[]
}

// A labelled select; a plain string option is its own label.
export function Select({ label, options, ...rest }: Props) {
  return (
    <Field label={label}>
      <select {...rest}>
        {options.map((option) => {
          const { value, label: text } = typeof option === 'string' ? { value: option, label: option } : option
          return <option key={value} value={value}>{text}</option>
        })}
      </select>
    </Field>
  )
}
