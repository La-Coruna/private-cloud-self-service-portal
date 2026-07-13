import axios from 'axios'

export interface NormalizedApiError {
  title: string
  code?: string
  message: string
  detail?: string
  fieldErrors: string[]
}

interface FastApiValidationError {
  loc?: Array<string | number>
  msg?: string
}

function toText(value: unknown): string | undefined {
  if (value == null) return undefined
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return undefined
}

function detailIfDifferent(message: string, detail: unknown): string | undefined {
  const detailText = toText(detail)
  return detailText && detailText !== message ? detailText : undefined
}

function toFieldErrors(detail: unknown): string[] {
  if (!Array.isArray(detail)) return []

  return detail
    .map((item: FastApiValidationError) => {
      const field = item.loc?.filter((part) => part !== 'body').join('.') ?? 'field'
      return item.msg ? `${field}: ${item.msg}` : undefined
    })
    .filter((item): item is string => Boolean(item))
}

export function normalizeApiError(error: unknown): NormalizedApiError {
  if (!axios.isAxiosError(error)) {
    return {
      title: '\uc694\uccad\uc744 \ucc98\ub9ac\ud558\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4',
      message: error instanceof Error ? error.message : '\uc54c \uc218 \uc5c6\ub294 \uc624\ub958\uac00 \ubc1c\uc0dd\ud588\uc2b5\ub2c8\ub2e4.',
      fieldErrors: [],
    }
  }

  if (!error.response) {
    return {
      title: '\uc11c\ubc84 \uc751\ub2f5\uc744 \ubc1b\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4',
      message: '\ud3ec\ud138 \uc8fc\uc18c\uc640 \ub124\ud2b8\uc6cc\ud06c \uc0c1\ud0dc\ub97c \ud655\uc778\ud55c \ub4a4 \ub2e4\uc2dc \uc2dc\ub3c4\ud574 \uc8fc\uc138\uc694.',
      fieldErrors: [],
    }
  }

  const data = error.response.data
  const status = error.response.status
  const title =
    status === 409 ? '\ud504\ub85c\uc81d\ud2b8\ub97c \uc0dd\uc131\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4' :
    status === 422 ? '\uc785\ub825\uac12\uc744 \ud655\uc778\ud574 \uc8fc\uc138\uc694' :
    status >= 400 && status < 500 ? '\uc694\uccad\uc774 \uac70\ubd80\ub418\uc5c8\uc2b5\ub2c8\ub2e4' :
    '\uc11c\ubc84 \uc624\ub958\uac00 \ubc1c\uc0dd\ud588\uc2b5\ub2c8\ub2e4'

  if (data && typeof data === 'object' && 'error' in data) {
    const payload = data as { error?: { code?: string; message?: string; detail?: unknown } }
    const message = payload.error?.message ?? '\ubc31\uc5d4\ub4dc\uac00 \uc694\uccad\uc744 \uac70\ubd80\ud588\uc2b5\ub2c8\ub2e4.'

    return {
      title,
      code: payload.error?.code,
      message,
      detail: detailIfDifferent(message, payload.error?.detail),
      fieldErrors: [],
    }
  }

  if (data && typeof data === 'object' && 'detail' in data) {
    const payload = data as { detail?: unknown }
    const fieldErrors = toFieldErrors(payload.detail)
    const message = fieldErrors.length > 0
      ? '\uc785\ub825 \ud544\ub4dc\uc5d0 \uc218\uc815\uc774 \ud544\uc694\ud55c \uac12\uc774 \uc788\uc2b5\ub2c8\ub2e4.'
      : toText(payload.detail) ?? '\ubc31\uc5d4\ub4dc\uac00 \uc694\uccad\uc744 \uac70\ubd80\ud588\uc2b5\ub2c8\ub2e4.'

    return {
      title,
      message,
      detail: fieldErrors.length > 0 ? undefined : detailIfDifferent(message, payload.detail),
      fieldErrors,
    }
  }

  if (data && typeof data === 'object' && 'message' in data) {
    return {
      title,
      message: toText((data as { message?: unknown }).message) ?? '\ubc31\uc5d4\ub4dc\uac00 \uc694\uccad\uc744 \uac70\ubd80\ud588\uc2b5\ub2c8\ub2e4.',
      fieldErrors: [],
    }
  }

  return {
    title,
    message: error.message || '\uc694\uccad \ucc98\ub9ac \uc911 \uc624\ub958\uac00 \ubc1c\uc0dd\ud588\uc2b5\ub2c8\ub2e4.',
    fieldErrors: [],
  }
}
