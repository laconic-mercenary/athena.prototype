import { useState, useRef, useEffect } from 'react'
import { marked } from 'marked'
import { sendChat, planReview } from '../api'

marked.setOptions({ breaks: true })

const GATE_BADGE_STYLE = {
  display: 'inline-block',
  fontSize: 8,
  fontWeight: 800,
  letterSpacing: 1.5,
  textTransform: 'uppercase',
  padding: '2px 6px',
  borderRadius: 3,
  background: '#1e3050',
  color: '#3b82f6',
  marginLeft: 8,
}

function PlanPreview({ plan, planReady, proceeding, error, onApprove, onRequestChanges }) {
  if (!plan) return null
  const committeeNames = Object.keys(plan.committees || {})
  const gates = plan.gates || []

  return (
    <div style={{ padding: '24px 20px', overflowY: 'auto', height: '100%' }}>
      <div style={{ fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', color: '#3b5270', marginBottom: 4 }}>
        Engagement Plan
      </div>
      <div style={{ fontSize: 10, color: '#475569', marginBottom: 20, lineHeight: 1.5 }}>
        {committeeNames.length} committee{committeeNames.length !== 1 ? 's' : ''} will run in sequence.
        Review the objectives below, then click Proceed.
      </div>

      {planReady ? (
        <div style={{ marginBottom: 20, padding: '10px 14px', background: '#071020', border: '1px solid #1e3050', borderRadius: 6, fontSize: 10, color: '#475569' }}>
          Review the plan above, then approve to start the engagement.
        </div>
      ) : committeeNames.length > 0 && (
        <div style={{ marginBottom: 20, padding: '10px 14px', background: '#071020', border: '1px solid #1e3050', borderRadius: 6, fontSize: 10, color: '#3b5270' }}>
          Orchestrator is revising the plan…
        </div>
      )}

      {committeeNames.map((name, i) => {
        const brief = plan.committees[name]
        const gate = gates.find(g => g.after === name)
        const isLast = i === committeeNames.length - 1

        return (
          <div key={name}>
            <div style={{
              background: '#0a121e',
              border: '1px solid #1e3050',
              borderRadius: 6,
              padding: '12px 14px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <span style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  width: 18, height: 18,
                  borderRadius: '50%',
                  background: '#1e3050',
                  color: '#64748b',
                  fontSize: 9,
                  fontWeight: 700,
                  flexShrink: 0,
                }}>
                  {i + 1}
                </span>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', letterSpacing: 0.5, textTransform: 'uppercase' }}>
                  {name}
                </span>
              </div>

              {(brief.objective || []).length > 0 && (
                <div style={{ paddingLeft: 26, marginBottom: 4 }}>
                  <div style={{ fontSize: 8, letterSpacing: 1, textTransform: 'uppercase', color: '#334155', marginBottom: 3 }}>
                    Objective
                  </div>
                  {(brief.objective || []).map((obj, j) => (
                    <div key={j} style={{ fontSize: 11, color: '#64748b', lineHeight: 1.5, marginBottom: 2 }}>
                      {obj}
                    </div>
                  ))}
                </div>
              )}

              {brief.constraints?.length > 0 && (
                <div style={{ paddingLeft: 26, marginTop: 6 }}>
                  <div style={{ fontSize: 8, letterSpacing: 1, textTransform: 'uppercase', color: '#334155', marginBottom: 3 }}>
                    Constraints
                  </div>
                  {brief.constraints.map((c, j) => (
                    <div key={j} style={{ fontSize: 10, color: '#475569', lineHeight: 1.5 }}>{c}</div>
                  ))}
                </div>
              )}

              {brief.emphasis?.length > 0 && (
                <div style={{ paddingLeft: 26, marginTop: 6 }}>
                  <div style={{ fontSize: 8, letterSpacing: 1, textTransform: 'uppercase', color: '#334155', marginBottom: 3 }}>
                    Emphasis
                  </div>
                  {brief.emphasis.map((e, j) => (
                    <div key={j} style={{ fontSize: 10, color: '#475569', lineHeight: 1.5 }}>{e}</div>
                  ))}
                </div>
              )}
            </div>

            {!isLast && (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '6px 0' }}>
                {gate ? (
                  <>
                    <div style={{ width: 1, height: 8, background: '#1e3050' }} />
                    <div style={{
                      background: '#0d1a2a',
                      border: '1px solid #1e4080',
                      borderRadius: 4,
                      padding: '4px 10px',
                      fontSize: 8,
                      color: '#3b82f6',
                      letterSpacing: 1.5,
                      textTransform: 'uppercase',
                      fontWeight: 700,
                    }}>
                      ⬡ Operator approval required
                    </div>
                    <div style={{ width: 1, height: 8, background: '#1e3050' }} />
                  </>
                ) : (
                  <div style={{ width: 1, height: 16, background: '#1e3050' }} />
                )}
              </div>
            )}
          </div>
        )
      })}
      {planReady && (
        <div style={{ marginTop: 24, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {error && (
            <div style={{ fontSize: 10, color: '#ef4444', textAlign: 'center' }}>{error}</div>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className="plan-review-btn plan-review-btn--reject"
              style={{ flex: 1 }}
              disabled={proceeding}
              onClick={onRequestChanges}
            >
              No, I want to make changes
            </button>
            <button
              className="plan-review-btn plan-review-btn--approve"
              style={{ flex: 1 }}
              disabled={proceeding}
              onClick={onApprove}
            >
              {proceeding ? 'Starting…' : 'Approve →'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export function OrchestratorDialog({ state, dispatch }) {
  const { engagement, dialogMessages, planReady, plan } = state

  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [proceeding, setProceeding] = useState(false)
const [error, setError] = useState(null)
  const messagesRef = useRef(null)
  const textareaRef = useRef(null)

  const awaitingReply = dialogMessages.length > 0 && dialogMessages[dialogMessages.length - 1].role === 'orch'

  useEffect(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight
    }
  }, [dialogMessages])

  async function sendMessage(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || sending || proceeding) return
    setSending(true)
    setError(null)
    dispatch({ type: 'DIALOG_OPERATOR_MESSAGE', payload: { text } })
    try {
      await sendChat(engagement.run_id, 'athena.orchestrator', text)
      setInput('')
    } catch (err) {
      setError(err.message)
    } finally {
      setSending(false)
    }
  }

  function handleRequestChanges() {
    setInput(prev => 'I want to make changes to the plan.\n\n' + prev)
    setTimeout(() => textareaRef.current?.focus(), 0)
  }

  async function handleProceed() {
    if (!planReady || proceeding) return
    setProceeding(true)
    setError(null)
    try {
      await planReview(engagement.run_id, 'approve')
      dispatch({ type: 'NAVIGATE', payload: 'dashboard' })
    } catch (err) {
      setError(err.message)
      setProceeding(false)
    }
  }

  return (
    <div className="dialog-shell">
      <div className="dialog-topbar">
        <span className="dialog-logo">Athena</span>
        <div className="dialog-steps">
          <span className="dialog-step dialog-step--done">Instructions</span>
          <span className="dialog-step-arrow">›</span>
          <span className="dialog-step dialog-step--active">Briefing</span>
          <span className="dialog-step-arrow">›</span>
          <span className="dialog-step dialog-step--next">Engagement</span>
        </div>
        <span className="dialog-run-id">{engagement.run_id}</span>
      </div>

      <div className="dialog-body">
        {/* ── Chat pane ── */}
        <div className="dialog-chat-pane">
          <div className="dialog-pane-header">
            <span className="dialog-agent-dot" />
            <span className="dialog-pane-label">Orchestrator</span>
          </div>

          <div className="dialog-messages" ref={messagesRef}>
            {dialogMessages.length === 0 && !planReady && (
              <div className="dialog-waiting">Waiting for orchestrator…</div>
            )}
            {dialogMessages.map((msg, i) => {
              const isOrch = msg.role === 'orch' || msg.role === 'orch-msg'
              return (
                <div key={i} className={`dialog-msg dialog-msg--${isOrch ? 'orch' : msg.role}`}>
                  <div className="dialog-msg-meta">
                    <span className={`dialog-msg-role dialog-msg-role--${isOrch ? 'orch' : msg.role}`}>
                      {isOrch ? 'Orchestrator' : 'Operator'}
                    </span>
                    <span className="dialog-msg-time">
                      {new Date(msg.ts).toLocaleTimeString('en-GB', {
                        hour: '2-digit', minute: '2-digit', second: '2-digit',
                      })}
                    </span>
                  </div>
                  {isOrch ? (
                    <div
                      className="dialog-msg-body dialog-msg-body--md"
                      dangerouslySetInnerHTML={{ __html: marked.parse(msg.text) }}
                    />
                  ) : (
                    <div className="dialog-msg-body">{msg.text}</div>
                  )}
                </div>
              )
            })}
          </div>

          <div className="dialog-input-wrap">
            <div className="dialog-input-row">
              <textarea
                ref={textareaRef}
                className="dialog-textarea"
                rows={2}
                value={input}
                onChange={e => setInput(e.target.value)}
                placeholder={awaitingReply ? 'Reply to orchestrator…' : 'Waiting for orchestrator…'}
                disabled={sending || proceeding}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(e) }
                }}
              />
              <button
                className="dialog-btn-send"
                onClick={sendMessage}
                disabled={sending || !input.trim() || proceeding}
              >
                Send
              </button>
            </div>
          </div>
        </div>

        {/* ── Plan preview pane ── */}
        <div
          className="dialog-ext-pane"
          style={{ display: planReady || plan ? undefined : 'none' }}
        >
          <div className="dialog-pane-header">
            <span className="dialog-pane-label">Engagement Plan</span>
          </div>
          <PlanPreview
            plan={plan}
            planReady={planReady}
            proceeding={proceeding}
            error={error}
            onApprove={handleProceed}
            onRequestChanges={handleRequestChanges}
          />
        </div>
      </div>
    </div>
  )
}
