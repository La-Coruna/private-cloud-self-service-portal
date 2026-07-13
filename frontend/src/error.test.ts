import { describe, expect, it } from 'vitest'

import { normalizeApiError } from './lib/error'

function axiosError(status: number, data: unknown) {
  return {
    isAxiosError: true,
    message: 'Request failed',
    response: { status, data },
  }
}

describe('normalizeApiError', () => {
  it('parses custom backend error responses', () => {
    const error = normalizeApiError(axiosError(409, {
      error: {
        code: 'DEMO_LIMIT_EXCEEDED',
        message: 'Too many active demo projects',
        detail: 'Delete an old demo project before creating another one.',
      },
    }))

    expect(error.title).toBe('\ud504\ub85c\uc81d\ud2b8\ub97c \uc0dd\uc131\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4')
    expect(error.code).toBe('DEMO_LIMIT_EXCEEDED')
    expect(error.message).toBe('Too many active demo projects')
    expect(error.detail).toBe('Delete an old demo project before creating another one.')
  })

  it('does not duplicate custom backend detail when it matches the message', () => {
    const error = normalizeApiError(axiosError(409, {
      error: {
        code: 'DEMO_REPLICA_LIMIT',
        message: 'Demo mode replicas cannot exceed 1',
        detail: 'Demo mode replicas cannot exceed 1',
      },
    }))

    expect(error.message).toBe('Demo mode replicas cannot exceed 1')
    expect(error.detail).toBeUndefined()
  })

  it('converts FastAPI validation details to field errors', () => {
    const error = normalizeApiError(axiosError(422, {
      detail: [
        { loc: ['body', 'replicas'], msg: 'Input should be less than or equal to 1' },
        { loc: ['body', 'image'], msg: 'Image is not allowed' },
      ],
    }))

    expect(error.fieldErrors).toEqual([
      'replicas: Input should be less than or equal to 1',
      'image: Image is not allowed',
    ])
  })

  it('does not duplicate FastAPI detail strings', () => {
    const error = normalizeApiError(axiosError(400, {
      detail: 'Demo mode replicas cannot exceed 1',
    }))

    expect(error.message).toBe('Demo mode replicas cannot exceed 1')
    expect(error.detail).toBeUndefined()
  })

  it('returns a friendly message for network errors', () => {
    const error = normalizeApiError({ isAxiosError: true, message: 'Network Error' })

    expect(error.title).toBe('\uc11c\ubc84 \uc751\ub2f5\uc744 \ubc1b\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4')
    expect(error.message).toContain('\ub124\ud2b8\uc6cc\ud06c')
  })
})
