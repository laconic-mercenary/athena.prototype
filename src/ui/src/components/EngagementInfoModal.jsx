import { useState } from 'react'

function fmtStarted(ts) {
  if (!ts) return '—'
  const d = new Date(ts)
  return d.toLocaleString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function Row({ label, children }) {
  return (
    <div className="eng-info-row">
      <span className="eng-info-label">{label}</span>
      <span className="eng-info-value">{children}</span>
    </div>
  )
}

export function EngagementInfoModal({ engagement, phase, committeeCount, onClose }) {
  const [copied, setCopied] = useState(false)

  async function copyId() {
    try {
      await navigator.clipboard.writeText(engagement.run_id || '')
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch { /* clipboard unavailable — no-op */ }
  }

  return (
    <div className="report-modal-overlay" onClick={onClose}>
      <div className="report-modal eng-info-modal" onClick={e => e.stopPropagation()}>
        <div className="report-modal-header" style={{ borderColor: '#3b82f6' }}>
          <span className="report-modal-title" style={{ color: '#3b82f6' }}>Engagement Info</span>
          <button className="report-modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="report-modal-body eng-info-body">
          <Row label="Run ID">
            <code className="eng-info-uuid">{engagement.run_id || '—'}</code>
            <button className="eng-info-copy" onClick={copyId}>{copied ? 'copied' : 'copy'}</button>
          </Row>
          <Row label="Status">{engagement.status || '—'}</Row>
          <Row label="Phase">{phase || '—'}</Row>
          <Row label="Committees">{committeeCount ?? '—'}</Row>
          <Row label="Started">{fmtStarted(engagement.startedAt)}</Row>
          {engagement.objective && (
            <div className="eng-info-objective">
              <span className="eng-info-label">Objective</span>
              <p>{engagement.objective}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
