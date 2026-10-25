// Shapes the API returns: cases, flows, runs, run events, the coverage map and suggested tests.

export type Mode = 'static' | 'fallback' | 'healed' | 'failed' | 'skipped'
export type Status = 'queued' | 'running' | 'passed' | 'failed' | 'error'
export type RunKind = 'run' | 'flow' | 'author' | 'compose' | 'crawl'
export type Vars = Record<string, string>

export interface Step {
  id: string
  action: 'goto' | 'click' | 'fill' | 'press' | 'hover'
  selector: string | null
  fallback_selectors: string[]
  frame: string | null
  value: string | null
  description: string
  expects: { kind: string; value: string } | null
  healed_count: number
}

export interface Assertion {
  assertion: string
  mode: 'deterministic' | 'jev'
}

export interface Heal {
  step: string
  old: string
  new: string
  at: string
  reason: string
}

export interface Case {
  name: string
  intent: string
  start_path: string
  steps: Step[]
  assertions: Assertion[]
  meta: { created_at: string; runs: number; heals: Heal[] }
}

export interface RunRef {
  id: string
  status: Status
  modes?: Mode[]
  finished_at?: string
}

export interface CaseSummary {
  name: string
  intent: string
  steps: number
  runs: number
  heals: number
  start_path: string
  updated_at: string
  last_run?: RunRef
  health: Health
}

// Over the case's last 10 finished runs; history is oldest first.
export interface Health {
  runs: number
  passed: number
  flaky: number
  avg_ms: number | null
  heals: number
  history: { id: string; status: Status; flaky: boolean }[]
}

export interface FlowCase {
  case: string
  vars: Vars
}

export interface Flow {
  name: string
  intent: string
  vars: Vars
  chain: FlowCase[]
  cleanup: FlowCase[]
}

export interface FlowSummary extends Flow {
  updated_at?: string
  last_run?: RunRef
}

export interface RunSummary {
  id: string
  kind: RunKind
  target: string
  intent?: string
  vars: Vars
  status: Status
  created_at: string
  finished_at?: string
  total_ms?: number
  healed?: number
  modes?: Mode[]
  ai_calls?: number
  error?: string
  attempts?: number
  flaky?: boolean
  retries?: number
}

export interface CaseDetail extends Case {
  updated_at: string
  runs: RunSummary[]
  health: Health
}

export interface FlowDetail extends Flow {
  updated_at: string
  runs: RunSummary[]
}

interface EventBase {
  seq: number
  at: string
}

export interface CaseEvent extends EventBase {
  kind: 'case'
  phase: 'start' | 'end'
  case: string
  stage: 'chain' | 'cleanup'
  passed?: boolean
  healed?: number
  total_ms?: number
  error?: string
}

export interface StepEvent extends EventBase {
  kind: 'step'
  i: number
  id: string
  description: string
  mode: Mode
  selector: string | null
  ms: number
  drift: boolean
  error: string | null
  path?: string
}

export interface AssertionEvent extends EventBase {
  kind: 'assertion'
  assertion: string
  mode: 'deterministic' | 'jev'
  passed: boolean
  reasoning: string
  confidence?: number | null
}

export interface DecisionEvent extends EventBase {
  kind: 'decision'
  operation: string
  label: string
  probability: number
  confidence: number
  latency_ms: number
  detail: string
}

export interface ActionEvent extends EventBase {
  kind: 'action'
  action: string
  description: string
  value?: string
  ok: boolean
  error?: string
}

export interface ShotEvent extends EventBase {
  kind: 'shot'
}

export interface NoteEvent extends EventBase {
  kind: 'note'
  level: 'info' | 'warn' | 'error'
  text: string
}

// Emitted right before a retry; n is 2 for the first retry.
export interface AttemptEvent extends EventBase {
  kind: 'attempt'
  n: number
}

export interface PageEvent extends EventBase {
  kind: 'page'
  path: string
  title: string
  controls: number
  links: number
  depth: number
}

export type RunEvent =
  | CaseEvent | StepEvent | AssertionEvent | DecisionEvent | ActionEvent | ShotEvent | NoteEvent | AttemptEvent | PageEvent

interface JevUsage {
  calls: number
  input_tokens: number
  latency_ms: number
  model: string | null
}

interface AnthropicUsage {
  calls: number
  input_tokens: number
  output_tokens: number
  cache_read_input_tokens: number
}

export interface Run extends RunSummary {
  events: RunEvent[]
  usage?: { jev?: JevUsage; anthropic?: AnthropicUsage }
}

export interface User {
  id: string
  email: string
  role: 'admin' | 'member'
  created_at: string
}

export interface Check {
  name: string
  ok: boolean
  detail: string
}

export interface SettingsHealth {
  checks: Check[]
  optional: { name: string; set: boolean; note: string }[]
  workers: number
}

export interface Control {
  role: string
  label: string
  kind: 'nav' | 'mutation' | 'destructive' | 'other'
}

export interface MapPage {
  path: string
  title: string
  controls: Control[]
  links: string[]
  cases: string[]
  last_seen: string
}

export interface MapSection {
  name: string
  covered: number
  total: number
  pages: MapPage[]
}

export interface Gap {
  path: string
  control: Control
  why: string
}

export interface AppMap {
  crawled_at: string | null
  sections: MapSection[]
  gaps: Gap[]
}

export interface Suggestion {
  id: string
  name: string
  intent: string
  why: string
  vars: Vars
  source: 'docs' | 'map' | 'both'
  status: 'open' | 'authored' | 'dismissed'
  case?: string
  run_id?: string
  run_status?: Status
  created_at: string
  created_by: string
}
