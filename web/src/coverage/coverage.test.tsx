import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { api } from '../api'
import type { MapSection, Suggestion } from '../types'
import { SectionBoard } from './Map'
import { SuggestForm } from './SuggestForm'
import { SuggestionRow } from './SuggestionRow'

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  const api = { ...actual.api, map: vi.fn(), settingsHealth: vi.fn(), dismissSuggestion: vi.fn(), authorSuggestion: vi.fn() }
  return { ...actual, api, settingsHealthQuery: { ...actual.settingsHealthQuery, queryFn: api.settingsHealth } }
})

const show = (ui: ReactNode) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter>{ui}</MemoryRouter>
  </QueryClientProvider>,
)

const page = (path: string, cases: string[]) => ({ path, title: path, controls: [], links: [], cases, last_seen: '2026-10-24T12:00:00Z' })
const SECTION: MapSection = {
  name: 'templates', covered: 1, total: 2,
  pages: [page('/:ws/templates', ['create-sms-template']), page('/:ws/templates/new', [])],
}

test('the map shows a covered page on surface with its case links and an uncovered one on surface-2', () => {
  show(<SectionBoard section={SECTION} />)
  expect(screen.getByText('templates · 1 of 2 covered')).toBeInTheDocument()
  expect(screen.getByText('/:ws/templates', { selector: 'span' }).parentElement).toHaveClass('surface')
  expect(screen.getByText('/:ws/templates/new', { selector: 'span' }).parentElement).toHaveClass('surface-2')
  expect(screen.getByRole('link', { name: 'create-sms-template' })).toHaveAttribute('href', '/cases/create-sms-template')
  expect(screen.getByText('No case visits it')).toBeInTheDocument()
})

const suggestion = (fields: Partial<Suggestion>): Suggestion => ({
  id: 'a1b2c3d4e5f6', name: 'delete-sms-template', intent: 'Delete the {{name}} template', why: 'No case deletes a template.',
  vars: { name: 'promo' }, source: 'map', status: 'open', created_at: '2026-10-24T12:00:00Z', created_by: 'qa@team.test', ...fields,
})

test('an open suggestion offers Author, and Dismiss calls the API', async () => {
  vi.mocked(api.dismissSuggestion).mockResolvedValue()
  show(<SuggestionRow suggestion={suggestion({})} selected={false} onSelect={() => {}} />)
  expect(screen.getByRole('button', { name: 'Author' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
  await waitFor(() => expect(api.dismissSuggestion).toHaveBeenCalledWith('a1b2c3d4e5f6'))
})

test('an authored suggestion shows its run status, then the case once the run passed', () => {
  const running = suggestion({ status: 'authored', run_id: 'r1', run_status: 'running', case: 'delete-sms-template' })
  const { unmount } = show(<SuggestionRow suggestion={running} selected={false} onSelect={() => {}} />)
  expect(screen.getByText('Running').closest('a')).toHaveAttribute('href', '/runs/r1')
  expect(screen.queryByRole('button', { name: 'Author' })).not.toBeInTheDocument()
  unmount()
  show(<SuggestionRow suggestion={{ ...running, run_status: 'passed' }} selected={false} onSelect={() => {}} />)
  expect(screen.getByRole('link', { name: 'Open case' })).toHaveAttribute('href', '/cases/delete-sms-template')
})

test('the suggest form is disabled with the reason when the Anthropic key is not set', async () => {
  vi.mocked(api.map).mockResolvedValue({ crawled_at: null, sections: [], gaps: [] })
  vi.mocked(api.settingsHealth).mockResolvedValue({
    checks: [], workers: 3, optional: [{ name: 'ANTHROPIC_API_KEY', set: false, note: '' }],
  })
  show(<SuggestForm primary pending={false} error={null} onSuggest={() => {}} />)
  fireEvent.change(screen.getByRole('textbox', { name: /Or paste text/ }), { target: { value: 'Release notes' } })
  expect(await screen.findByText(/Suggesting needs/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Suggest' })).toBeDisabled()
})
