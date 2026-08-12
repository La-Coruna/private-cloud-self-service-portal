import { formatKstDateTimeWithLabel } from '../lib/date'
import type { PlatformStatus } from '../lib/types'

interface PlatformStatusBannerProps {
  status: PlatformStatus
}

export function PlatformStatusBanner({ status }: PlatformStatusBannerProps) {
  if (status.status === 'AVAILABLE') return null

  const unavailable = status.status === 'UNAVAILABLE'

  return (
    <section
      className={`platform-status-banner platform-status-${status.status.toLowerCase()}`}
      role={unavailable ? 'alert' : 'status'}
    >
      <div>
        <strong>{unavailable ? 'GKE 플랫폼을 사용할 수 없음' : 'GKE 워크로드 복구 중'}</strong>
        <p>{status.message}</p>
      </div>
      <time dateTime={status.checked_at}>
        확인 시각: {formatKstDateTimeWithLabel(status.checked_at)}
      </time>
    </section>
  )
}