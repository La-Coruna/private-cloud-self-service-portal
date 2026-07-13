import { describe, expect, it } from 'vitest'

import { formatKstDateTime, formatKstDateTimeWithLabel } from './date'

describe('KST date formatting', () => {
  it('treats timestamp strings without timezone as UTC and formats them in KST', () => {
    expect(formatKstDateTime('2026-07-12T17:00:00')).toContain('2026. 07. 13.')
    expect(formatKstDateTime('2026-07-12T17:00:00')).toContain('02:00')
  })

  it('formats Z timestamps in KST', () => {
    expect(formatKstDateTime('2026-07-12T17:00:00Z')).toContain('2026. 07. 13.')
    expect(formatKstDateTime('2026-07-12T17:00:00Z')).toContain('02:00')
  })

  it('respects timestamps that already include an offset', () => {
    expect(formatKstDateTime('2026-07-12T17:00:00+09:00')).toContain('2026. 07. 12.')
    expect(formatKstDateTime('2026-07-12T17:00:00+09:00')).toContain('17:00')
  })

  it('returns a dash for empty or invalid values', () => {
    expect(formatKstDateTime(null)).toBe('-')
    expect(formatKstDateTime(undefined)).toBe('-')
    expect(formatKstDateTime('not-a-date')).toBe('-')
  })

  it('adds a KST label for valid timestamps', () => {
    expect(formatKstDateTimeWithLabel('2026-07-12T17:00:00Z')).toMatch(/KST$/)
    expect(formatKstDateTimeWithLabel(undefined)).toBe('-')
  })
})