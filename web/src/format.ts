// Formatting for durations, dates, counts and names.

export function duration(ms?: number): string {
  if (ms == null) return '-'
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`
}

export function ago(iso?: string, now = Date.now()): string {
  if (!iso) return '-'
  const minutes = Math.floor((now - Date.parse(iso)) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)}h ago`
  if (minutes < 7 * 24 * 60) return `${Math.floor(minutes / (24 * 60))}d ago`
  return iso.slice(0, 10)
}

export function count(n: number, noun: string): string {
  return `${n.toLocaleString('en')} ${noun}${n === 1 ? '' : 's'}`
}

// The n most recently updated items.
export const newest = <T extends { updated_at?: string }>(items: T[], n: number) =>
  [...items].sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? '')).slice(0, n)

export function isToday(iso: string, now = new Date()): boolean {
  return new Date(iso).toDateString() === now.toDateString()
}

// The {{var}}s an intent declares, in order, once each.
export function intentVars(intent: string): string[] {
  return [...new Set([...intent.matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map((m) => m[1]))]
}

export const NAME_PATTERN = '[a-z0-9][a-z0-9\\-]{0,63}'

// The name the author agent gives a case when none is set; must match the backend.
export function deriveName(intent: string): string {
  return (intent.toLowerCase().match(/[a-z0-9]+/g) ?? []).slice(0, 5).join('-') || 'case'
}

// A run's title; authoring and compose runs without a name have no target yet.
export function runTitle(run: { target: string; kind: string }): string {
  return run.target || (run.kind === 'compose' ? 'New flow' : 'New case')
}

// Who checks an assertion: Jev or a deterministic check.
export function checkedBy(mode: 'deterministic' | 'jev'): string {
  return mode === 'jev' ? 'Jev' : 'deterministic'
}
