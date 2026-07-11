import type { ProjectStatus } from '../lib/types'

interface StatusBadgeProps {
  status: ProjectStatus | string
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return <span className={`status-badge status-${status.toLowerCase()}`}>{status}</span>
}