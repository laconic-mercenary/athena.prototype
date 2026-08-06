import { useState, useEffect } from 'react'
import { listArtifacts } from '../api'

const CLASSIFICATION_ORDER = ['signal_critical', 'signal_warn', 'signal_info', 'noise', 'unknown']

function classificationLabel(cls) {
  const map = { signal_critical: 'CRITICAL', signal_warn: 'WARN', signal_info: 'INFO', noise: 'NOISE', unknown: '?' }
  return map[cls] || cls
}

function classificationColor(cls) {
  if (cls === 'signal_critical') return '#ef4444'
  if (cls === 'signal_warn')     return '#f97316'
  if (cls === 'signal_info')     return '#22c55e'
  return '#64748b'
}

export function ArtifactTable({ runId, committees, onOpen }) {
  const [artifacts, setArtifacts] = useState([])

  useEffect(() => {
    if (!runId) return
    listArtifacts(runId).then(setArtifacts).catch(() => {})
  }, [runId])

  const allFindings = Object.entries(committees).flatMap(([committee, data]) =>
    (data.findings || []).map(f => ({ ...f, committee }))
  ).sort((a, b) =>
    CLASSIFICATION_ORDER.indexOf(a.classification) - CLASSIFICATION_ORDER.indexOf(b.classification)
  )

  return (
    <div className="artifact-panel">
      {allFindings.length > 0 && (
        <section className="findings-section">
          <h3 className="panel-heading">Findings</h3>
          <div className="findings-list">
            {allFindings.map((f, i) => (
              <div key={i} className="finding-row" style={{ borderLeftColor: classificationColor(f.classification) }}>
                <span className="finding-badge" style={{ color: classificationColor(f.classification) }}>
                  {classificationLabel(f.classification)}
                </span>
                <span className="finding-summary">{f.summary}</span>
                <span className="finding-committee">{f.committee}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {artifacts.length > 0 && (
        <section className="artifacts-section">
          <h3 className="panel-heading">Artifacts</h3>
          <div className="artifact-list">
            {artifacts.map(a => {
              const committee = committees[a.name]
              const incomplete = committee?.incomplete
              return (
                <button
                  key={a.name}
                  className="artifact-row"
                  onClick={() => onOpen && onOpen(a.name)}
                >
                  <span className="artifact-name">{a.name}</span>
                  {incomplete && (
                    <span style={{
                      fontSize: 8, color: '#f97316',
                      background: '#1a0e00', borderRadius: 2,
                      padding: '1px 4px', marginLeft: 4,
                    }}>
                      INCOMPLETE
                    </span>
                  )}
                  <span className="artifact-size">{(a.size / 1024).toFixed(1)} KB</span>
                </button>
              )
            })}
          </div>
        </section>
      )}

      {allFindings.length === 0 && artifacts.length === 0 && (
        <div className="panel-empty">No findings yet</div>
      )}
    </div>
  )
}
