import { useState, useEffect } from 'react'
import { getArtifact } from '../api'

export function ReportModal({ runId, name, title, accent, incomplete, onClose }) {
  const [content, setContent] = useState(null)
  const [error, setError]     = useState(null)

  useEffect(() => {
    let cancelled = false
    getArtifact(runId, name)
      .then(text => {
        if (!cancelled) {
          // Pretty-print if valid JSON, else show raw
          try {
            setContent(JSON.stringify(JSON.parse(text), null, 2))
          } catch {
            setContent(text)
          }
        }
      })
      .catch(err => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [runId, name])

  return (
    <div className="report-modal-overlay" onClick={onClose}>
      <div className="report-modal" onClick={e => e.stopPropagation()}>
        <div className="report-modal-header" style={{ borderColor: accent }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span className="report-modal-title" style={{ color: accent }}>{title}</span>
            {incomplete && (
              <span style={{
                fontSize: 8, fontWeight: 700, letterSpacing: 1.5,
                textTransform: 'uppercase', color: '#f97316',
                background: '#1a0e00', border: '1px solid #f9731644',
                borderRadius: 3, padding: '2px 6px',
              }}>
                INCOMPLETE
              </span>
            )}
          </div>
          <button className="report-modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="report-modal-body">
          {error && <div className="report-modal-error">Failed to load artifact: {error}</div>}
          {!error && !content && <div className="report-modal-loading">Loading…</div>}
          {content && (
            <pre style={{
              margin: 0, padding: '16px',
              fontSize: 11, color: '#94a3b8',
              lineHeight: 1.6, whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              fontFamily: 'monospace',
            }}>
              {content}
            </pre>
          )}
        </div>
      </div>
    </div>
  )
}
