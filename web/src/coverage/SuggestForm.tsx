import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import { anthropicKeySet, api, settingsHealthQuery } from '../api'
import { Button } from '../forms/Button'
import { Field } from '../forms/Field'
import { mapQuery } from './Map'
import field from '../forms/Field.module.css'
import form from '../styles/form.module.css'
import styles from './Suggestions.module.css'

interface Props {
  primary: boolean
  pending: boolean
  error: Error | null
  onSuggest: (request: Parameters<typeof api.suggest>[0]) => void
}

// Where suggestions come from: docs URLs, pasted text and the map's gaps.
export function SuggestForm({ primary, pending, error, onSuggest }: Props) {
  const health = useQuery(settingsHealthQuery)
  const map = useQuery(mapQuery)
  const [params] = useSearchParams()
  const [urls, setUrls] = useState([''])
  const [text, setText] = useState('')
  const [useMap, setUseMap] = useState<boolean>()
  const [count, setCount] = useState(8)
  const keySet = anthropicKeySet(health.data)
  const mapped = useMap ?? (params.has('map') || Boolean(map.data?.sections.length))
  const docsUrls = urls.map((url) => url.trim()).filter(Boolean)
  const nothingToRead = !docsUrls.length && !text.trim() && !mapped
  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSuggest({ docs_urls: docsUrls, text, use_map: mapped, count })
  }
  return (
    <form className={`tile ${form.form} ${form.panel} ${styles.form}`} onSubmit={submit}>
      <h2>From</h2>
      <fieldset className={field.field}>
        <legend className="small muted">Docs URLs</legend>
        <span className={styles.urls}>
          {urls.map((url, i) => (
            <span key={i} className={styles.url}>
              <input type="url" aria-label={`Docs URL ${i + 1}`} placeholder="https://" value={url}
                onChange={(e) => setUrls(urls.map((u, j) => (j === i ? e.target.value : u)))} />
              {urls.length > 1 && <Button variant="text" onClick={() => setUrls(urls.filter((_, j) => j !== i))}>Remove</Button>}
            </span>
          ))}
          {urls.length < 5 && <Button variant="text" onClick={() => setUrls([...urls, ''])}>Add URL</Button>}
        </span>
        <span className="small muted">Only these pages are read. Links on them are not followed.</span>
      </fieldset>
      <Field label="Or paste text" hint="Release notes, a spec or a help article.">
        <textarea rows={8} maxLength={20_000} value={text} onChange={(e) => setText(e.target.value)} />
      </Field>
      <label className={form.check}>
        <input type="checkbox" checked={mapped} onChange={(e) => setUseMap(e.target.checked)} />Use the map's gaps
      </label>
      <Field label="How many">
        <input type="number" required min={1} max={15} value={count} onChange={(e) => setCount(Number(e.target.value))} />
      </Field>
      <p className="small muted">Your saved cases are read too, so it won't suggest one you already have.</p>
      {keySet === false && (
        <p className="small">Suggesting needs <code>ANTHROPIC_API_KEY</code> in <code>.env</code>. <Link to="/settings">Settings</Link></p>
      )}
      <Button variant={primary ? 'primary' : 'secondary'} type="submit" disabled={keySet === false || nothingToRead || pending}>
        {pending ? 'Reading the docs' : primary ? 'Suggest' : 'Suggest more'}
      </Button>
      {error && <p className="fail" role="alert">{error.message}</p>}
    </form>
  )
}
