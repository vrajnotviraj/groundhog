import { render, screen } from '@testing-library/react'
import { StatusTile } from './StatusTile'

test.each([
  ['passed', 'Passed', 'pass'],
  ['failed', 'Failed', 'fail'],
  ['error', 'Error', 'fail'],
  ['running', 'Running', 'surface-2'],
  ['queued', 'Queued', 'surface-2'],
] as const)('%s reads %s on a %s tile', (status, label, tone) => {
  render(<StatusTile status={status} />)
  expect(screen.getByText(label)).toHaveClass(tone)
})
