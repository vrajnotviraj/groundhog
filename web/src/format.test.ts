import { ago, count, deriveName, duration, intentVars, isToday } from './format'

test('duration reads ms, seconds and minutes', () => {
  expect(duration(420)).toBe('420ms')
  expect(duration(3200)).toBe('3.2s')
  expect(duration(134_000)).toBe('2m 14s')
  expect(duration(undefined)).toBe('-')
})

test('ago reads recent times in words and old ones as a date', () => {
  const now = Date.parse('2026-10-24T12:00:00Z')
  expect(ago('2026-10-24T11:59:40Z', now)).toBe('just now')
  expect(ago('2026-10-24T11:58:00Z', now)).toBe('2m ago')
  expect(ago('2026-10-24T09:00:00Z', now)).toBe('3h ago')
  expect(ago('2026-10-22T12:00:00Z', now)).toBe('2d ago')
  expect(ago('2026-09-01T12:00:00Z', now)).toBe('2026-09-01')
})

test('count pluralises and prints zero', () => {
  expect(count(0, 'run')).toBe('0 runs')
  expect(count(1, 'case')).toBe('1 case')
  expect(count(1200, 'step')).toBe('1,200 steps')
})

test('isToday compares calendar days', () => {
  const now = new Date(2026, 9, 24, 15)
  expect(isToday(new Date(2026, 9, 24, 1).toISOString(), now)).toBe(true)
  expect(isToday(new Date(2026, 9, 23, 23).toISOString(), now)).toBe(false)
})

test('intentVars lists each var once in order', () => {
  expect(intentVars('create {{name}} then find {{ name }} under {{query}}')).toEqual(['name', 'query'])
})

test('deriveName matches the author agent', () => {
  expect(deriveName('Create an SMS template named X and verify')).toBe('create-an-sms-template-named')
  expect(deriveName('!!!')).toBe('case')
})
