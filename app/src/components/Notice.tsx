interface NoticeProps {
  readonly title: string
  readonly error: Error
  readonly onRetry?: () => void
}

/** A readable load failure, announced to screen readers. */
export function Notice({ title, error, onRetry }: NoticeProps) {
  return (
    <div className="notice" role="alert">
      <p className="notice__title">{title}</p>
      <p className="notice__body">{error.message}</p>
      {onRetry ? (
        <button type="button" className="button" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  )
}
