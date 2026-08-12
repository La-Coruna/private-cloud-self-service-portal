import { useQuery } from '@tanstack/react-query'

import { getPlatformStatus } from '../lib/api'

export function usePlatformStatus() {
  return useQuery({
    queryKey: ['platform-status'],
    queryFn: getPlatformStatus,
    refetchInterval: 15_000,
  })
}