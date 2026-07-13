import type { NormalizedApiError } from '../lib/error'

interface ErrorCardProps {
  error: NormalizedApiError
}

export function ErrorCard({ error }: ErrorCardProps) {
  return (
    <div className="error-card" role="alert">
      <div className="error-card-header">
        <strong>{error.title}</strong>
        {error.code && <span className="error-code">{error.code}</span>}
      </div>
      <p>{error.message}</p>
      {error.detail && <p>{error.detail}</p>}
      {error.fieldErrors.length > 0 && (
        <ul className="field-error-list">
          {error.fieldErrors.map((item) => <li key={item}>{item}</li>)}
        </ul>
      )}
    </div>
  )
}
