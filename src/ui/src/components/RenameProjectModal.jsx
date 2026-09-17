import { useState } from 'react'
import { renameProject } from '../api'

export function RenameProjectModal({ currentName, onClose, onRenamed }) {
  const [name, setName] = useState(currentName)
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed || trimmed === currentName) return
    setSubmitting(true)
    setError(null)
    try {
      const project = await renameProject(currentName, trimmed)
      onRenamed(project.name)
    } catch (err) {
      setError(err.message)
      setSubmitting(false)
    }
  }

  return (
    <div className="chat-overlay" onClick={onClose}>
      <div className="chat-panel" onClick={e => e.stopPropagation()} style={{ maxWidth: 420 }}>
        <div className="chat-header">
          <div>
            <div className="chat-title">Rename project</div>
            <div className="chat-subtitle">{currentName}</div>
          </div>
          <button className="chat-close" onClick={onClose}>✕</button>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <input
            autoFocus
            className="modal-input"
            value={name}
            onChange={e => setName(e.target.value)}
            maxLength={100}
            disabled={submitting}
          />
          {error && <p className="request-error" style={{ marginTop: 0 }}>{error}</p>}
          <div className="chat-actions" style={{ padding: 0, justifyContent: 'flex-end', gap: 8 }}>
            <button
              type="button"
              className="plan-review-btn"
              style={{ border: '1px solid #334155', color: '#94a3b8', background: 'transparent' }}
              onClick={onClose}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="plan-review-btn plan-review-btn--approve"
              disabled={submitting || !name.trim() || name.trim() === currentName}
            >
              {submitting ? 'Renaming…' : 'Rename'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
