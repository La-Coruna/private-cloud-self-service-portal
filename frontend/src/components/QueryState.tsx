import type { ReactNode } from 'react'

interface QueryStateProps {
  isLoading: boolean
  isError: boolean
  error: unknown
  children: ReactNode
}

export function QueryState({ isLoading, isError, error, children }: QueryStateProps) {
  if (isLoading) return <div className="notice">불러오는 중입니다.</div>
  if (isError) {
    const message = error instanceof Error ? error.message : '요청을 처리하지 못했습니다.'
    return <div className="notice error">{message}</div>
  }
  return <>{children}</>
}