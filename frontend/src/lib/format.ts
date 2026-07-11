export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '-'
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

export function textOrDash(value: string | null | undefined): string {
  return value && value.trim().length > 0 ? value : '-'
}