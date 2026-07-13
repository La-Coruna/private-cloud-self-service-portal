function parseUtcDate(value: string | Date): Date {
  if (value instanceof Date) return value

  const trimmed = value.trim()
  const hasTimezone = /Z$|[+-]\d{2}:\d{2}$/.test(trimmed)
  return new Date(hasTimezone ? trimmed : `${trimmed}Z`)
}

export function formatKstDateTime(value: string | Date | null | undefined): string {
  if (!value) return '-'

  const date = parseUtcDate(value)
  if (Number.isNaN(date.getTime())) return '-'

  return new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

export function formatKstDateTimeWithLabel(value: string | Date | null | undefined): string {
  const formatted = formatKstDateTime(value)
  return formatted === '-' ? '-' : `${formatted} KST`
}