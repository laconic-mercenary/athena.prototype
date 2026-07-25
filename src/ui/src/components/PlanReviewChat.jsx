import { useState } from 'react'
import { planReview } from '../api'

export function PlanReviewChat({ runId, committee, digest, onApproved, onRejected, onClose }) {
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
            <div className="chat-subtitle">Review the committee output before proceeding</div>
          </div>
          <button className="chat-close" onClick={onClose}>✕</button>
        </div>

        {digest ? (
          <div className="chat-thread" style={{ flex: 1 }}>
            <pre style={{
              margin: 0, padding: '12px 16px',
              fontSize: 10, color: '#64748b',
              lineHeight: 1.6, whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              fontFamily: 'inherit',
            }}>
              {digest}
            </pre>
          </div>
        ) : (
          <div className="chat-empty" style={{ flex: 1 }}>
            No digest available — approve or reject based on the artifact.
          </div>
        )}

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
