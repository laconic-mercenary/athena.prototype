import { useState, useEffect } from 'react'
import { marked } from 'marked'
import { getArtifact } from '../api'

export function ReportModal({ runId, name, title, accent, incomplete, onClose }) {
  const [raw, setRaw]         = useState(null)
  const [rendered, setRendered] = useState(null)   // markdown from render_full(), or null if N/A
  const [tab, setTab]         = useState('rendered')
  const [error, setError]     = useState(null)

  useEffect(() => {
    let cancelled = false
    // Raw JSON (pretty-printed) and the schema's rendered markdown, in parallel.
    getArtifact(runId, name)
      .then(text => {
        if (cancelled) return
        try { setRaw(JSON.stringify(JSON.parse(text), null, 2)) } catch { setRaw(text) }
      })
      .catch(err => { if (!cancelled) setError(err.message) })

    getArtifact(runId, name, { render: true })
      .then(md => {
        if (cancelled) return
        // The endpoint falls back to raw JSON when an artifact isn't renderable; treat a
        // JSON-looking payload as "no rendered view" so we don't show a code blob as prose.
        const looksJson = md.trim().startsWith('{') || md.trim().startsWith('[')
        setRendered(looksJson ? null : md)
      })
      .catch(() => { /* rendered view is optional */ })

    return () => { cancelled = true }
  }, [runId, name])

  // Default to the rendered tab when it's available, else raw.
  const activeTab = rendered ? tab : 'raw'

  return (
    <div className="report-modal-overlay" onClick={onClose}>
      <div className="report-modal" onClick={e => e.stopPropagation()}>
        <div className="report-modal-header" style={{ borderColor: accent }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
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
            {rendered && (
              <div className="report-modal-tabs">
                <button
                  className={`report-modal-tab ${activeTab === 'rendered' ? 'is-active' : ''}`}
                  onClick={() => setTab('rendered')}
                >
                  Rendered
                </button>
                <button
                  className={`report-modal-tab ${activeTab === 'raw' ? 'is-active' : ''}`}
                  onClick={() => setTab('raw')}
                >
                  Raw JSON
                </button>
              </div>
            )}
          </div>
          <button className="report-modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="report-modal-body">
          {error && <div className="report-modal-error">Failed to load artifact: {error}</div>}
          {!error && !raw && <div className="report-modal-loading">Loading…</div>}
          {!error && activeTab === 'rendered' && rendered && (
            <div
              className="md-render"
              dangerouslySetInnerHTML={{ __html: marked.parse(rendered) }}
            />
          )}
          {!error && activeTab === 'raw' && raw && (
            <pre style={{
              margin: 0, padding: '16px',
              fontSize: 11, color: '#94a3b8',
              lineHeight: 1.6, whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              fontFamily: 'monospace',
            }}>
              {raw}
            </pre>
          )}
        </div>
      </div>
    </div>
  )
}
