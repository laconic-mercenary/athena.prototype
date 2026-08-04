import { useState } from 'react'

// Abuse/quality report affordance for AI chat messages. Eye candy for now — Submit
// just closes; there is no server handler yet. Every AI message renders <ReportButton/>;
// the parent chat view owns one <FeedbackModal/> that the button opens.

const CATEGORIES = [
  'Offensive Content',
  'Factually Incorrect',
  'Poor Tone',
  'Unsafe / Harmful',
  'Unhelpful',
  'Other',
]

// Thumbs-down icon button shown on each AI message.
export function ReportButton({ onClick }) {
  return (
    <button
      type="button"
      className="msg-report-btn"
      title="Report this response"
      aria-label="Report this response"
      onClick={onClick}
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3z" />
        <path d="M17 2h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17" />
      </svg>
    </button>
  )
}

export function FeedbackModal({ open, onClose }) {
  const [selected, setSelected] = useState([])
  const [note, setNote] = useState('')

  if (!open) return null

  const toggle = (c) =>
    setSelected(s => (s.includes(c) ? s.filter(x => x !== c) : [...s, c]))

  // No server handler yet — Cancel and Submit both just reset and close.
  const close = () => {
    setSelected([])
    setNote('')
    onClose()
  }

  return (
    <div className="chat-overlay" onClick={close}>
      <div
        className="chat-panel chat-panel--review"
        onClick={e => e.stopPropagation()}
        style={{ maxWidth: 460 }}
      >
        <div className="chat-header">
          <div>
            <div className="chat-title">Report this response</div>
            <div className="chat-subtitle">Tell us what was wrong</div>
          </div>
          <button className="chat-close" onClick={close}>✕</button>
        </div>

        <div style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {CATEGORIES.map(c => {
              const on = selected.includes(c)
              return (
                <button
                  key={c}
                  type="button"
                  onClick={() => toggle(c)}
                  style={{
                    padding: '6px 12px', borderRadius: 6, cursor: 'pointer',
                    fontSize: 12, fontFamily: 'inherit',
                    border: `1px solid ${on ? '#ef4444' : '#334155'}`,
                    background: on ? 'rgba(239,68,68,0.12)' : 'transparent',
                    color: on ? '#fca5a5' : '#94a3b8',
                    transition: 'color 0.15s, border-color 0.15s, background 0.15s',
                  }}
                >
                  {c}
                </button>
              )
            })}
          </div>
          <textarea
            className="dialog-textarea"
            rows={3}
            placeholder="Add any details (optional)"
            value={note}
            onChange={e => setNote(e.target.value)}
          />
        </div>

        <div className="chat-actions" style={{ padding: '12px 16px', gap: 8, justifyContent: 'flex-end' }}>
          <button
            type="button"
            className="plan-review-btn"
            style={{ border: '1px solid #334155', color: '#94a3b8', background: 'transparent' }}
            onClick={close}
          >
            Cancel
          </button>
          <button
            type="button"
            className="plan-review-btn plan-review-btn--reject"
            onClick={close}
          >
            Submit
          </button>
        </div>
      </div>
    </div>
  )
}
