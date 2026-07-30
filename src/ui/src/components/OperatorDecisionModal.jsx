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
  onAccept,             // async (selectedChoiceId?) => void
  onRedo,               // async (suggestion: string) => void
  onSkip,               // async () => void  (steps only)
  showSkip = false,
  choices,              // optional [{ id, label, title }] — renders a winner picker (element gate)
  defaultChoiceId,      // the leader's pick, pre-selected in the picker
  onOpenArtifact,
  onClose,
  acceptLabel = 'Accept →',
  redoLabel = 'Redo',
  redoIcon = '↻',
  redoPlaceholder = 'What should change on the redo? (optional)',
}) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  const [redoOpen, setRedoOpen] = useState(false)
  const [suggestion, setSuggestion] = useState('')
  const [selected, setSelected] = useState(defaultChoiceId)

  const hasChoices = Array.isArray(choices) && choices.length > 0
  const overriding = hasChoices && selected !== defaultChoiceId

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

        {hasChoices && (
          <div className="gate-choices" style={{ padding: '10px 16px 2px', display: 'flex', flexDirection: 'column', gap: 6 }}>
            {choices.map(c => {
              const isSel = c.id === selected
              const isLeader = c.id === defaultChoiceId
              return (
                <button
                  type="button"
                  key={c.id}
                  className="gate-choice"
                  onClick={() => setSelected(c.id)}
                  style={{
                    textAlign: 'left', padding: '8px 10px', borderRadius: 6, cursor: 'pointer',
                    border: `1px solid ${isSel ? '#3b82f6' : '#1e293b'}`,
                    background: isSel ? 'rgba(59,130,246,0.10)' : 'transparent',
                    display: 'flex', flexDirection: 'column', gap: 6,
                  }}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{
                      width: 12, height: 12, borderRadius: '50%', flexShrink: 0,
                      border: `2px solid ${isSel ? '#3b82f6' : '#475569'}`,
                      background: isSel ? '#3b82f6' : 'transparent',
                    }} />
                    <span style={{ flex: 1, fontSize: 12, color: '#cbd5e1' }}>
                      <span style={{ fontWeight: 600 }}>{c.label}</span>
                      {c.title && <span style={{ color: '#64748b' }}> · {c.title}</span>}
                    </span>
                    {isLeader && (
                      <span style={{ fontSize: 9, color: '#22c55e', border: '1px solid #22c55e', borderRadius: 4, padding: '1px 5px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                        Leader's pick
                      </span>
                    )}
                  </span>
                  {c.output && (
                    <pre style={{
                      margin: 0, padding: '6px 8px 6px 22px',
                      fontSize: 10, color: '#94a3b8', lineHeight: 1.5,
                      whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'inherit',
                      maxHeight: 120, overflowY: 'auto',
                    }}>
                      {c.output}
                    </pre>
                  )}
                </button>
              )
            })}
          </div>
        )}

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
              placeholder={redoPlaceholder}
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
            // Picker mode (element gate) takes no suggestion — Redo is one click. The
            // suggestion textarea flow is only for prose-review gates (committee / step).
            hasChoices ? (
              <button
                type="button"
                className="plan-review-btn plan-review-btn--redo"
                disabled={pending}
                onClick={() => run(() => onRedo())}
              >
                {redoLabel} {redoIcon}
              </button>
            ) : redoOpen ? (
              <button
                type="button"
                className="plan-review-btn plan-review-btn--redo"
                disabled={pending}
                onClick={() => run(() => onRedo(suggestion.trim()))}
              >
                {pending ? 'Processing…' : `Confirm ${redoLabel}`}
              </button>
            ) : (
              <button
                type="button"
                className="plan-review-btn plan-review-btn--redo"
                disabled={pending}
                onClick={() => setRedoOpen(true)}
              >
                {redoLabel} {redoIcon}
              </button>
            )
          )}

          <button
            type="button"
            className="plan-review-btn plan-review-btn--approve"
            disabled={pending}
            onClick={() => run(() => onAccept(selected))}
          >
            {pending ? 'Processing…' : overriding ? 'Confirm Override →' : acceptLabel}
          </button>
        </div>

      </div>
    </div>
  )
}
