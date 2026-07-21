import { useState } from 'react'
import { startEngagement } from '../api'

export function EngagementRequest({ onSubmit }) {
  const [instructions, setInstructions] = useState('')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    const text = instructions.trim()
    if (!text) return
    setSubmitting(true)
    setError(null)
    try {
      const { run_id } = await startEngagement(text)
      onSubmit(run_id)
    } catch (err) {
      setError(err.message)
      setSubmitting(false)
    }
  }

  return (
    <div className="request-page">
      <div className="request-card">
        <h1 className="request-title">Athena</h1>
        <form onSubmit={handleSubmit} className="request-form">
          <label className="request-label" htmlFor="instructions">
            Engagement instructions
          </label>
          <textarea
            id="instructions"
            className="request-textarea"
            value={instructions}
            onChange={e => setInstructions(e.target.value)}
            placeholder="Describe the target and scope of the engagement…"
            rows={8}
            maxLength={8192}
            disabled={submitting}
          />
          <div className="request-footer">
            <span className="request-char-count">{instructions.length} / 8192</span>
            <button
              type="submit"
              className="request-submit"
              disabled={submitting || !instructions.trim()}
            >
              {submitting ? 'Starting…' : 'Start engagement'}
            </button>
          </div>
          {error && <p className="request-error">{error}</p>}
        </form>
      </div>
    </div>
  )
}
