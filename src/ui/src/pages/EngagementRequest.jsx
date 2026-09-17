import { useState, useEffect } from 'react'
import { startProjectEngagement, listArtifacts } from '../api'
import { EngagementList } from '../components/EngagementList'

export function EngagementRequest({ project, onBack, onSubmit }) {
  const [instructions, setInstructions] = useState('')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const [seedEnabled, setSeedEnabled] = useState(false)
  const [seedRunId, setSeedRunId] = useState(null)
  const [seedCommittee, setSeedCommittee] = useState('')
  const [seedArtifacts, setSeedArtifacts] = useState([])

  useEffect(() => {
    if (!seedRunId) { setSeedArtifacts([]); return }
    listArtifacts(seedRunId).then(setSeedArtifacts).catch(() => setSeedArtifacts([]))
  }, [seedRunId])

  function handleSelectSeedRun(engagement) {
    setSeedRunId(engagement.run_id)
    setSeedCommittee('')
  }

  async function handleSubmit(e) {
    e.preventDefault()
    const text = instructions.trim()
    if (!text || !project) return
    setSubmitting(true)
    setError(null)
    const seed = (seedEnabled && seedRunId)
      ? { project, run_id: seedRunId, committee: seedCommittee || null }
      : null
    try {
      const { run_id } = await startProjectEngagement(project, text, null, seed)
      onSubmit(run_id, text, seed)
    } catch (err) {
      setError(err.message)
      setSubmitting(false)
    }
  }

  return (
    <div className="request-page">
      <div className="request-card">
        {onBack && (
          <button type="button" className="back-link" onClick={onBack}>← Projects</button>
        )}
        <h1 className="request-title">Athena</h1>
        {project && <p className="request-subtitle">Project: {project}</p>}
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
            rows={12}
            maxLength={8192}
            disabled={submitting}
          />

          <label className="seed-picker-toggle">
            <input
              type="checkbox"
              checked={seedEnabled}
              onChange={e => {
                setSeedEnabled(e.target.checked)
                if (!e.target.checked) { setSeedRunId(null); setSeedCommittee('') }
              }}
              disabled={submitting}
            />
            Build on a previously completed engagement
          </label>

          {seedEnabled && (
            <div className="seed-picker-panel">
              <EngagementList
                projectName={project}
                statusFilter="completed"
                onSelect={handleSelectSeedRun}
                selectedRunId={seedRunId}
              />
              {seedRunId && seedArtifacts.length > 0 && (
                <select
                  className="seed-picker-select"
                  value={seedCommittee}
                  onChange={e => setSeedCommittee(e.target.value)}
                >
                  <option value="">(auto — terminal committee)</option>
                  {seedArtifacts.map(a => (
                    <option key={a.name} value={a.name}>{a.name}</option>
                  ))}
                </select>
              )}
            </div>
          )}

          <div className="request-footer">
            <span className="request-char-count">{instructions.length} / 8192</span>
            <button
              type="submit"
              className="request-submit"
              disabled={submitting || !instructions.trim() || !project}
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
