import type { ReactNode } from 'react'

import { ErrorCard } from './ErrorCard'
import { normalizeApiError } from '../lib/error'

interface QueryStateProps {
  isLoading: boolean
  isError: boolean
  error: unknown
  children: ReactNode
}

export function QueryState({ isLoading, isError, error, children }: QueryStateProps) {
  if (isLoading) return <div className="notice">Loading data.</div>
  if (isError) return <ErrorCard error={normalizeApiError(error)} />
  return <>{children}</>
}
