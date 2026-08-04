import { useState, useRef, useEffect } from 'react'
import { reportChat } from '../api'
import { FeedbackModal, ReportButton } from './FeedbackModal'

export function ReportChat({ runId, onClose }) {
  const [thread, setThread]   = useState([])
  const [input, setInput]     = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError]     = useState(null)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const threadRef = useRef(null)

  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight
  }, [thread])

  async function handleSubmit(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || sending) return
    setSending(true)
    setError(null)
    setThread(prev => [...prev, { role: 'operator', text, ts: Date.now() }])
    setInput('')
    try {
      const res = await reportChat(runId, text)
      setThread(prev => [...prev, { role: 'agent', text: res.reply, ts: Date.now() }])
    } catch (err) {
      setError(err.message)
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="chat-overlay" onClick={onClose}>
      <div className="chat-panel chat-panel--review" onClick={e => e.stopPropagation()}>

        <div className="chat-header">
          <div>
            <div className="chat-title">Engagement Debrief</div>
            <div className="chat-subtitle">ask questions about the report and findings</div>
          </div>
          <button className="chat-close" onClick={onClose}>✕</button>
        </div>

        <div className="chat-thread" ref={threadRef}>
          {thread.length === 0 && (
            <div className="chat-empty">
              Ask anything about the reconnaissance findings, the plan, the data collected, or the final risk assessment.
            </div>
          )}
          {thread.map((m, i) => (
            <div key={i} className={`chat-msg${m.role === 'agent' ? ' chat-msg--agent' : ''}`}>
              <div className="chat-msg-meta">
                <span className={`chat-msg-role${m.role === 'agent' ? ' chat-msg-role--agent' : ''}`}>
                  {m.role === 'agent' ? 'Athena' : 'Operator'}
                </span>
                <span className="chat-msg-time">
                  {new Date(m.ts).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                </span>
                {m.role === 'agent' && <ReportButton onClick={() => setFeedbackOpen(true)} />}
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
            placeholder="Ask about the engagement…"
            rows={3}
            maxLength={2000}
            disabled={sending}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit(e) } }}
          />
          <div className="chat-actions">
            {error && <span className="chat-error">{error}</span>}
            <button type="submit" className="chat-send" disabled={sending || !input.trim()}>
              {sending ? 'Asking…' : 'Ask'}
            </button>
          </div>
        </form>

        <FeedbackModal open={feedbackOpen} onClose={() => setFeedbackOpen(false)} />
      </div>
    </div>
  )
}
