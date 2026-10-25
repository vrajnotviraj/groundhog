import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { api, casesQuery, settingsHealthQuery } from '../api'
import type { CaseSummary } from '../types'
import { Cases } from './Cases'

const CASE: CaseSummary = {
  name: 'create-sms-template', intent: 'Create a template named {{name}}', steps: 5, runs: 2, heals: 0,
  start_path: '/:ws/home', updated_at: '2026-10-24T12:00:00Z',
  health: { runs: 2, passed: 1, flaky: 1, avg_ms: 7400, heals: 0, history: [
    { id: 'r1', status: 'failed', flaky: false }, { id: 'r2', status: 'passed', flaky: true },
  ] },
}

beforeEach(() => {
  vi.spyOn(casesQuery, 'queryFn').mockResolvedValue([CASE])
  vi.spyOn(settingsHealthQuery, 'queryFn').mockResolvedValue({ checks: [], optional: [], workers: 3 })
})

afterEach(() => vi.restoreAllMocks())

test('checking a case shows the selection bar, which runs it as a batch', async () => {
  const batch = vi.spyOn(api, 'batchRun').mockResolvedValue({ run_ids: ['r3'] })
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><Cases /></MemoryRouter>
    </QueryClientProvider>,
  )
  expect(await screen.findByRole('img', { name: '1 of 2 passed, 1 flaky' })).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Selected cases' })).toBeNull()

  fireEvent.click(screen.getByRole('checkbox', { name: 'Select create-sms-template' }))
  expect(screen.getByRole('region', { name: 'Selected cases' })).toHaveTextContent('1 selected')
  fireEvent.click(screen.getByRole('button', { name: 'Run 1 case' }))
  expect(await screen.findByText('1 run queued')).toBeInTheDocument()
  expect(batch).toHaveBeenCalledWith({ cases: ['create-sms-template'], flows: [] })
})
