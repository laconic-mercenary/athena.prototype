import { useState, useRef, useEffect } from 'react'
import { planReviewChat } from '../api'

export function PlanReviewChat({ runId, onApproved, onRejected, onClose }) {
  const [thread, setThread]   = useState([])
  const [input, setInput]     = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError]     = useState(null)
  const threadRef = useRef(null)

  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight
  }, [thread])

  async function send(message) {
    if (sending) return
    setSending(true)
    setError(null)
    const userMsg = { role: 'operator', text: message, ts: Date.now() }
    setThread(prev => [...prev, userMsg])
    setInput('')
    try {
      const res = await planReviewChat(runId, message)
      if (res.action === 'approved') { onApproved(); return }
      if (res.action === 'rejected') { onRejected(); return }
      if (res.reply) {
        setThread(prev => [...prev, { role: 'agent', text: res.reply, ts: Date.now() }])
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setSending(false)
    }
  }

  function handleSubmit(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text) return
    send(text)
  }

  return (
    <div className="chat-overlay" onClick={onClose}>
      <div className="chat-panel chat-panel--review" onClick={e => e.stopPropagation()}>

        <div className="chat-header">
          <div>
            <div className="chat-title">Planning Lead</div>
            <div className="chat-subtitle">plan review · awaiting your approval</div>
          </div>
          <button className="chat-close" onClick={onClose}>✕</button>
        </div>

        <div className="chat-thread" ref={threadRef}>
          {thread.length === 0 && (
            <div className="chat-empty">
              Ask questions about the reconnaissance findings or the proposed plan. Type <strong>approve</strong> or <strong>reject</strong> when ready.
            </div>
          )}
          {thread.map((m, i) => (
            <div key={i} className={`chat-msg${m.role === 'agent' ? ' chat-msg--agent' : ''}`}>
              <div className="chat-msg-meta">
                <span className={`chat-msg-role${m.role === 'agent' ? ' chat-msg-role--agent' : ''}`}>
                  {m.role === 'agent' ? 'Planning Lead' : 'Operator'}
                </span>
                <span className="chat-msg-time">
                  {new Date(m.ts).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                </span>
              </div>
              <div className="chat-msg-body">{m.text}</div>
            </div>
          ))}
          {sending && (
            <div className="chat-msg chat-msg--agent">
              <div className="chat-msg-body plan-review-thinking">thinking…</div>
            </div>
          )}
        </div>

        <form onSubmit={handleSubmit} className="chat-form">
          <textarea
            className="chat-input"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Ask a question about the plan…"
            rows={3}
            maxLength={2000}
            disabled={sending}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit(e) } }}
          />
          <div className="chat-actions plan-review-actions">
            {error && <span className="chat-error">{error}</span>}
            <button type="submit" className="chat-send" disabled={sending || !input.trim()}>
              {sending ? 'Asking…' : 'Ask'}
            </button>
            <button
              type="button"
              className="plan-review-btn plan-review-btn--reject"
              disabled={sending}
              onClick={() => send('reject')}
            >
              Reject ✕
            </button>
            <button
              type="button"
              className="plan-review-btn plan-review-btn--approve"
              disabled={sending}
              onClick={() => send('approve')}
            >
              Approve →
            </button>
          </div>
        </form>

      </div>
    </div>
  )
}
