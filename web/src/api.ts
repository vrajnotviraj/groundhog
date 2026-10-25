// Typed calls to the console API.
import type {
  AppMap, Case, CaseDetail, CaseSummary, Flow, FlowDetail, FlowSummary, Run, RunSummary, SettingsHealth, Suggestion,
  User, Vars,
} from './types'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export interface RunOptions {
  vars?: Vars
  heal?: boolean
  headed?: boolean
  retries?: 0 | 1 | 2
}

interface RunFilters {
  limit?: number
  kind?: string
  status?: string
  target?: string
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    credentials: 'include',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
  return response.status === 204 ? (undefined as T) : response.json()
}

// FastAPI says what went wrong in `detail`: a sentence, or a list of field errors.
async function errorMessage(response: Response): Promise<string> {
  const { detail } = await response.json().catch(() => ({ detail: response.statusText }))
  if (Array.isArray(detail)) return detail.map((d) => `${d.loc.slice(1).join('.')}: ${d.msg}`).join('\n')
  return String(detail || response.statusText)
}

const get = <T>(path: string) => request<T>('GET', path)
const encode = encodeURIComponent

export const api = {
  login: (email: string, password: string) => request<void>('POST', '/auth/login', { email, password }),
  logout: () => request<void>('POST', '/auth/logout'),
  me: () => get<{ email: string; role: User['role'] }>('/auth/me'),
  health: () => get<{ mongo: boolean; version: string }>('/health'),

  cases: () => get<CaseSummary[]>('/cases'),
  case: (name: string) => get<CaseDetail>(`/cases/${encode(name)}`),
  saveCase: (name: string, body: Case) => request<void>('PUT', `/cases/${encode(name)}`, body),
  deleteCase: (name: string) => request<void>('DELETE', `/cases/${encode(name)}`),
  runCase: (name: string, options: RunOptions = {}) =>
    request<{ run_id: string }>('POST', `/cases/${encode(name)}/run`, options),
  authorCase: (body: { intent: string; name?: string; vars?: Vars; start?: string; headed?: boolean }) =>
    request<{ run_id: string }>('POST', '/cases/author', body),

  flows: () => get<FlowSummary[]>('/flows'),
  flow: (name: string) => get<FlowDetail>(`/flows/${encode(name)}`),
  saveFlow: (name: string, body: Flow) => request<void>('PUT', `/flows/${encode(name)}`, body),
  deleteFlow: (name: string) => request<void>('DELETE', `/flows/${encode(name)}`),
  runFlow: (name: string, options: RunOptions = {}) =>
    request<{ run_id: string }>('POST', `/flows/${encode(name)}/run`, options),
  composeFlow: (body: { intent: string }) =>
    request<{ run_id: string }>('POST', '/flows/compose', body),

  runs: (filters: RunFilters = {}) => {
    const query = new URLSearchParams(Object.entries(filters).filter(([, v]) => v).map(([k, v]) => [k, String(v)]))
    return get<RunSummary[]>(`/runs?${query}`)
  },
  run: (id: string) => get<Run>(`/runs/${encode(id)}`),
  batchRun: (body: { cases: string[]; flows: string[]; retries?: 0 | 1 | 2; heal?: boolean }) =>
    request<{ run_ids: string[] }>('POST', '/runs/batch', body),
  cancelRun: (id: string) => request<void>('POST', `/runs/${encode(id)}/cancel`),
  deleteRun: (id: string) => request<void>('DELETE', `/runs/${encode(id)}`),
  shotUrl: (id: string, seq: number) => `/api/runs/${encode(id)}/shots/${seq}`,
  eventsUrl: (id: string, after: number) => `/api/runs/${encode(id)}/events?after=${after}`,

  map: () => get<AppMap>('/map'),
  crawl: (body: { scope: string; max_pages: number; headed: boolean }) =>
    request<{ run_id: string }>('POST', '/map/crawl', body),

  suggestions: () => get<Suggestion[]>('/suggestions'),
  suggest: (body: { docs_urls: string[]; text: string; use_map: boolean; count: number }) =>
    request<Suggestion[]>('POST', '/suggestions', body),
  authorSuggestion: (id: string) => request<{ run_id: string }>('POST', `/suggestions/${encode(id)}/author`),
  dismissSuggestion: (id: string) => request<void>('POST', `/suggestions/${encode(id)}/dismiss`),
  deleteSuggestion: (id: string) => request<void>('DELETE', `/suggestions/${encode(id)}`),

  settingsHealth: () => get<SettingsHealth>('/settings/health'),
  checkLogin: () => request<{ ok: boolean; detail: string }>('POST', '/settings/check-login'),
  users: () => get<User[]>('/users'),
  addUser: (body: { email: string; password: string; role: User['role'] }) => request<User>('POST', '/users', body),
  removeUser: (id: string) => request<void>('DELETE', `/users/${encode(id)}`),
}

export const meQuery = { queryKey: ['me'], queryFn: api.me }
export const casesQuery = { queryKey: ['cases'], queryFn: api.cases }
export const anthropicKeySet = (h?: SettingsHealth) => h?.optional.find((o) => o.name === 'ANTHROPIC_API_KEY')?.set

export const settingsHealthQuery = { queryKey: ['settings-health'], queryFn: api.settingsHealth, staleTime: 60_000 }

export const isAdmin = (me?: { role: User['role'] }) => me?.role === 'admin'
