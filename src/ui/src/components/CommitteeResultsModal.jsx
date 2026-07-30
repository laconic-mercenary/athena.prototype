import { useState, useEffect } from 'react'
import { getArtifact, revealArtifact } from '../api'

const TABS = ['summary', 'artifact']

// Readonly text block with a copy-to-clipboard button in the upper right.
function CopyableText({ value, color, minHeight = 220 }) {
  const [copied, setCopied] = useState(false)
  const [failed, setFailed] = useState(false)
  async function copy() {
    setFailed(false)
    // Prefer the async clipboard API; fall back to execCommand for non-secure contexts.
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value)
      } else {
        const ta = document.createElement('textarea')
        ta.value = value
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.select()
        const ok = document.execCommand('copy')
        document.body.removeChild(ta)
        if (!ok) throw new Error('copy failed')
      }
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setFailed(true)
      setTimeout(() => setFailed(false), 2000)
    }
  }
  return (
    <div style={{ position: 'relative', padding: '14px 16px' }}>
      <button
        type="button"
        onClick={copy}
        title="Copy to clipboard"
        style={{
          position: 'absolute', top: 22, right: 26, zIndex: 2,
          fontSize: 9, fontWeight: 700, letterSpacing: 0.5,
          color: failed ? '#ef4444' : copied ? '#22c55e' : `${color}bb`,
          background: '#0b1524',
          border: `1px solid ${failed ? '#ef4444' : copied ? '#22c55e' : color + '55'}`,
          borderRadius: 4, padding: '3px 9px', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 4,
        }}
      >
        {failed ? '✕ Failed' : copied ? '✓ Copied' : '⧉ Copy'}
      </button>
      <textarea
        readOnly
        value={value}
        onFocus={e => e.target.select()}
        style={{
          width: '100%', minHeight, maxHeight: 420, resize: 'vertical',
          background: '#07101f', border: '1px solid #1e3050', borderRadius: 6,
          padding: '12px 14px', color: '#94a3b8', fontSize: 11, lineHeight: 1.6,
          fontFamily: 'monospace', outline: 'none', boxSizing: 'border-box',
          whiteSpace: 'pre', overflow: 'auto',
        }}
      />
    </div>
  )
}

export function CommitteeResultsModal({
  runId,
  name,
  color,
  digest,
  incomplete,
  onClose,
  onDiscuss,
}) {
  const [tab, setTab] = useState('summary')
  const [artifact, setArtifact] = useState(null)
  const [artifactError, setArtifactError] = useState(null)
  const [revealing, setRevealing] = useState(false)
  const [revealError, setRevealError] = useState(null)

  useEffect(() => {
    if (tab !== 'artifact' || artifact !== null) return
    let cancelled = false
    getArtifact(runId, name)
      .then(text => {
        if (cancelled) return
        try {
          setArtifact(JSON.stringify(JSON.parse(text), null, 2))
        } catch {
          setArtifact(text)
        }
      })
      .catch(err => { if (!cancelled) setArtifactError(err.message) })
    return () => { cancelled = true }
  }, [tab, runId, name, artifact])

  async function handleReveal() {
    setRevealing(true)
    setRevealError(null)
    try {
      await revealArtifact(runId, name)
    } catch (err) {
      setRevealError(err.message)
    } finally {
      setRevealing(false)
    }
  }

  const title = name.replace(/-/g, ' ').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())

  return (
    <div className="report-modal-overlay" onClick={onClose}>
      <div
        className="report-modal"
        style={{ maxWidth: 580, display: 'flex', flexDirection: 'column' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="report-modal-header" style={{ borderColor: color }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span className="report-modal-title" style={{ color }}>{title}</span>
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

        {/* Tabs */}
        <div style={{
          display: 'flex', gap: 0, borderBottom: '1px solid #1e3050',
          padding: '0 16px',
        }}>
          {TABS.map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                padding: '8px 14px', fontSize: 10, fontWeight: 700,
                letterSpacing: 1.2, textTransform: 'uppercase',
                color: tab === t ? color : '#334155',
                borderBottom: tab === t ? `2px solid ${color}` : '2px solid transparent',
                marginBottom: -1,
              }}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Body */}
        <div className="report-modal-body" style={{ flex: 1, minHeight: 0 }}>
          {tab === 'summary' && (
            digest ? (
              <CopyableText value={digest} color={color} />
            ) : (
              <div style={{ padding: '16px 20px', fontSize: 11, color: '#334155', fontStyle: 'italic' }}>
                No summary available — switch to Artifact for full output.
              </div>
            )
          )}

          {tab === 'artifact' && (
            <div>
              {artifactError && (
                <div style={{ padding: 16, color: '#ef4444', fontSize: 11 }}>
                  Failed to load: {artifactError}
                </div>
              )}
              {!artifactError && !artifact && (
                <div style={{ padding: 16, color: '#334155', fontSize: 11 }}>Loading…</div>
              )}
              {artifact && <CopyableText value={artifact} color={color} minHeight={280} />}
            </div>
          )}
        </div>

        {/* Footer actions */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '12px 16px',
          borderTop: '1px solid #1e3050',
        }}>
          <button
            type="button"
            className="plan-review-btn"
            style={{
              border: '1px solid #334155',
              color: '#64748b',
              background: 'transparent',
              opacity: revealing ? 0.5 : 1,
            }}
            onClick={handleReveal}
            disabled={revealing}
          >
            {revealing ? 'Opening…' : 'Show in Finder'}
          </button>
          {revealError && (
            <span style={{ fontSize: 10, color: '#ef4444' }}>{revealError}</span>
          )}
          <div style={{ flex: 1 }} />
          {onDiscuss && (
            <button
              type="button"
              className="plan-review-btn"
              style={{
                border: `1px solid ${color}44`,
                color,
                background: 'transparent',
              }}
              onClick={() => { onClose(); onDiscuss() }}
            >
              Discuss
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
