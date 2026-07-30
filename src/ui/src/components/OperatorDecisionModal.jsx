import { useState } from 'react'

// Reusable operator decision widget. Used now for the committee gate (Accept / Redo)
// and designed to be reused for step-level review later (pass showSkip + onSkip).
// The parent supplies the action callbacks (which call the API); this component only
// owns presentation + the Redo-suggestion field. See projects/202607/BRIEFING.md.
export function OperatorDecisionModal({
  title,
  subtitle,
  body,                 // digest / step output to review
  redoAvailable = true, // false when the manifest declares no retry/iterate edge
  onAccept,             // async () => void
  onRedo,               // async (suggestion: string) => void
  onSkip,               // async () => void  (steps only)
  showSkip = false,
  onOpenArtifact,
  onClose,
  acceptLabel = 'Accept →',
  redoLabel = 'Redo',
}) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  const [redoOpen, setRedoOpen] = useState(false)
  const [suggestion, setSuggestion] = useState('')

  async function run(fn) {
    if (pending) return
    setPending(true)
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(err.message)
      setPending(false)
    }
  }

  return (
    <div className="chat-overlay" onClick={onClose}>
      <div className="chat-panel chat-panel--review" onClick={e => e.stopPropagation()}>

        <div className="chat-header">
          <div>
            <div className="chat-title">{title}</div>
            {subtitle && <div className="chat-subtitle">{subtitle}</div>}
          </div>
          <button className="chat-close" onClick={onClose}>✕</button>
        </div>

        <div className="chat-thread" style={{ flex: 1 }}>
          {body ? (
            <pre style={{
              margin: 0, padding: '12px 16px',
              fontSize: 10, color: '#64748b',
              lineHeight: 1.6, whiteSpace: 'pre-wrap',
              wordBreak: 'break-word', fontFamily: 'inherit',
            }}>
              {body}
            </pre>
          ) : (
            <div className="chat-empty">
              No digest available — open the artifact for full context before deciding.
            </div>
          )}
        </div>

        {redoOpen && (
          <div style={{ padding: '0 16px 4px' }}>
            <textarea
              className="dialog-textarea"
              rows={2}
              placeholder="What should change on the redo? (optional)"
              value={suggestion}
              onChange={e => setSuggestion(e.target.value)}
              autoFocus
            />
          </div>
        )}

        <div className="chat-actions plan-review-actions" style={{ padding: '12px 16px', gap: 8 }}>
          {error && <span className="chat-error">{error}</span>}

          {onOpenArtifact && (
            <button
              type="button"
              className="plan-review-btn"
              style={{ border: '1px solid #334155', color: '#94a3b8', background: 'transparent' }}
              onClick={onOpenArtifact}
            >
              Artifact ↗
            </button>
          )}

          {showSkip && onSkip && (
            <button
              type="button"
              className="plan-review-btn plan-review-btn--reject"
              disabled={pending}
              onClick={() => run(onSkip)}
            >
              Skip
            </button>
          )}

          {redoAvailable && (
            redoOpen ? (
              <button
                type="button"
                className="plan-review-btn plan-review-btn--redo"
                disabled={pending}
                onClick={() => run(() => onRedo(suggestion.trim()))}
              >
                {pending ? 'Processing…' : 'Confirm Redo ↻'}
              </button>
            ) : (
              <button
                type="button"
                className="plan-review-btn plan-review-btn--redo"
                disabled={pending}
                onClick={() => setRedoOpen(true)}
              >
                {redoLabel} ↻
              </button>
            )
          )}

          <button
            type="button"
            className="plan-review-btn plan-review-btn--approve"
            disabled={pending}
            onClick={() => run(onAccept)}
          >
            {pending ? 'Processing…' : acceptLabel}
          </button>
        </div>

      </div>
    </div>
  )
}
