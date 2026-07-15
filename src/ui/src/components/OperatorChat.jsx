import { useState, useRef, useEffect } from 'react'
import { sendChat } from '../api'

const CLASSIFICATION_COLOR = {
  signal_critical: '#ef4444',
  signal_warn:     '#f97316',
  signal_info:     '#3b82f6',
}

const CLASSIFICATION_LABEL = {
  signal_critical: 'CRITICAL',
  signal_warn:     'WARN',
  signal_info:     'INFO',
}

export function OperatorChat({ runId, agentId, agentTitle, findings, focusFindings, onClose }) {
  const [tab, setTab] = useState(focusFindings && findings?.length ? 'findings' : 'chat')
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)
  const threadRef = useRef(null)

  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight
    }
  }, [messages])

  async function handleSend(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || sending) return
    const msg = { text, ts: Date.now() }
    setMessages(prev => [...prev, msg])
    setInput('')
    setSending(true)
    setError(null)
    try {
      await sendChat(runId, agentId, text)
    } catch (err) {
      setError(err.message)
    } finally {
      setSending(false)
    }
  }

  const alertFindings = (findings || []).filter(
    f => f.classification === 'signal_critical' || f.classification === 'signal_warn'
  )
  const hasFindings = alertFindings.length > 0

  return (
    <div className="chat-overlay" onClick={onClose}>
      <div className="chat-panel" onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="chat-header">
          <div>
            <div className="chat-title">{agentTitle}</div>
            <div className="chat-subtitle">mid-run injection</div>
          </div>
          <button className="chat-close" onClick={onClose}>✕</button>
        </div>

        {/* Tabs — only show if there are alert findings */}
        {hasFindings && (
          <div className="chat-tabs">
            <button
              className={`chat-tab${tab === 'chat' ? ' chat-tab--active' : ''}`}
              onClick={() => setTab('chat')}
            >
              Chat
            </button>
            <button
              className={`chat-tab${tab === 'findings' ? ' chat-tab--active' : ''}`}
              onClick={() => setTab('findings')}
            >
              Findings {alertFindings.length > 0 && <span className="chat-tab-badge">{alertFindings.length}</span>}
            </button>
          </div>
        )}

        {/* Findings tab */}
        {tab === 'findings' && (
          <div className="chat-findings">
            {alertFindings.map((f, i) => {
              const color = CLASSIFICATION_COLOR[f.classification] || '#64748b'
              const label = CLASSIFICATION_LABEL[f.classification] || f.classification
              return (
                <div key={i} className="chat-finding-row" style={{ borderLeftColor: color }}>
                  <span className="chat-finding-badge" style={{ color }}>{label}</span>
                  <span className="chat-finding-text">{f.summary}</span>
                </div>
              )
            })}
          </div>
        )}

        {/* Chat tab */}
        {tab === 'chat' && (
          <>
            <div className="chat-thread" ref={threadRef}>
              {messages.length === 0 && (
                <div className="chat-empty">
                  Messages sent here are injected into this agent's queue during its run.
                </div>
              )}
              {messages.map((m, i) => (
                <div key={i} className="chat-msg">
                  <div className="chat-msg-meta">
                    <span className="chat-msg-role">Operator</span>
                    <span className="chat-msg-time">
                      {new Date(m.ts).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </span>
                  </div>
                  <div className="chat-msg-body">{m.text}</div>
                </div>
              ))}
            </div>

            <form onSubmit={handleSend} className="chat-form">
              <textarea
                className="chat-input"
                value={input}
                onChange={e => setInput(e.target.value)}
                placeholder="Inject context into agent queue…"
                rows={3}
                maxLength={2000}
                disabled={sending}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(e) } }}
              />
              <div className="chat-actions">
                {error && <span className="chat-error">{error}</span>}
                <button type="submit" className="chat-send" disabled={sending || !input.trim()}>
                  {sending ? 'Sending…' : 'Send'}
                </button>
              </div>
            </form>
          </>
        )}

      </div>
    </div>
  )
}
