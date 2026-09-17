export function ConfirmModal({ title, body, confirmLabel = 'Confirm', onConfirm, onCancel }) {
  return (
    <div className="chat-overlay" onClick={onCancel}>
      <div className="chat-panel" onClick={e => e.stopPropagation()} style={{ maxWidth: 420 }}>
        <div className="chat-header">
          <div>
            <div className="chat-title">{title}</div>
          </div>
          <button className="chat-close" onClick={onCancel}>✕</button>
        </div>
        <div style={{ padding: '14px 16px', color: 'var(--text)', fontSize: 12, lineHeight: 1.5 }}>
          {body}
        </div>
        <div className="chat-actions" style={{ padding: '12px 16px', gap: 8, justifyContent: 'flex-end' }}>
          <button
            type="button"
            className="plan-review-btn"
            style={{ border: '1px solid #334155', color: '#94a3b8', background: 'transparent' }}
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            className="plan-review-btn plan-review-btn--reject"
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
