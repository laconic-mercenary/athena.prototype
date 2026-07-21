import { useState, useEffect } from 'react'
import { marked } from 'marked'
import { getArtifactMarkdown } from '../api'

marked.setOptions({ breaks: true })

/**
 * Modal that fetches a rendered markdown report (plan.md, report.md, …) for a
 * run and displays it. The artifact is produced atomically by its committee, so
 * this shows the final content — no live updating needed. Mount only once the
 * committee's artifact_emitted event has fired (the .md exists on disk by then).
 */
export function ReportModal({ runId, name, title, accent, onClose }) {
  const [html, setHtml] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    getArtifactMarkdown(runId, name)
      .then(md => { if (!cancelled) setHtml(marked.parse(md)) })
      .catch(err => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [runId, name])

  return (
    <div className="report-modal-overlay" onClick={onClose}>
      <div className="report-modal" onClick={e => e.stopPropagation()}>
        <div className="report-modal-header" style={{ borderColor: accent }}>
          <span className="report-modal-title" style={{ color: accent }}>{title}</span>
          <button className="report-modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="report-modal-body">
          {error && <div className="report-modal-error">Failed to load report: {error}</div>}
          {!error && !html && <div className="report-modal-loading">Loading report…</div>}
          {html && (
            <div
              className="report-modal-md"
              dangerouslySetInnerHTML={{ __html: html }}
            />
          )}
        </div>
      </div>
    </div>
  )
}
