import { useState } from 'react'
import { planReview } from '../api'

export function PlanReviewChat({ runId, committee, digest, onApproved, onRejected, onOpenArtifact, onClose }) {
  const [pending, setPending] = useState(false)
  const [error, setError]     = useState(null)

  async function handleAction(action) {
    if (pending) return
    setPending(true)
    setError(null)
    try {
      await planReview(runId, action)
      if (action === 'approve') onApproved()
      else onRejected()
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
            <div className="chat-title">{committee || 'Gate'} · Review</div>
            <div className="chat-subtitle">Orchestrator has staged this output for your approval</div>
          </div>
          <button className="chat-close" onClick={onClose}>✕</button>
        </div>

        <div className="chat-thread" style={{ flex: 1 }}>
          {digest ? (
            <pre style={{
              margin: 0, padding: '12px 16px',
              fontSize: 10, color: '#64748b',
              lineHeight: 1.6, whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              fontFamily: 'inherit',
            }}>
              {digest}
            </pre>
          ) : (
            <div className="chat-empty">
              No digest available — open the artifact for full context before deciding.
            </div>
          )}
        </div>

        <div className="chat-actions plan-review-actions" style={{ padding: '12px 16px', gap: 8 }}>
          {error && <span className="chat-error">{error}</span>}
          <button
            type="button"
            className="plan-review-btn plan-review-btn--reject"
            disabled={pending}
            onClick={() => handleAction('reject')}
          >
            Reject ✕
          </button>
          {onOpenArtifact && committee && (
            <button
              type="button"
              className="plan-review-btn"
              style={{ border: '1px solid #334155', color: '#94a3b8', background: 'transparent' }}
              onClick={onOpenArtifact}
            >
              Artifact ↗
            </button>
          )}
          <button
            type="button"
            className="plan-review-btn plan-review-btn--approve"
            disabled={pending}
            onClick={() => handleAction('approve')}
          >
            {pending ? 'Processing…' : 'Approve →'}
          </button>
        </div>

      </div>
    </div>
  )
}
