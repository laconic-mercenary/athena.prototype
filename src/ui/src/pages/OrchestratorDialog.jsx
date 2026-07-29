import { useState, useRef, useEffect } from 'react'
import { marked } from 'marked'
import { sendChat, planReview } from '../api'

marked.setOptions({ breaks: true })

const ORCH = 'athena.orchestrator'

// Canned revision instructions sent to the orchestrator when a gate switch is flipped.
// Toggles and free-form chat both reach the plan the same way — via a plan revision — so switch
// state stays derived from plan.gates (single source of truth). See BRIEFING.md §5.
// Only "pause" switches (approval gates) are wired here; traversal-gating switches (#5) stay
// disabled until the manifest's declared transitions are surfaced to the UI (BRIEFING.md §8).
const SWITCH_MESSAGES = {
  everyCommittee: {
    on: 'Require operator approval at every committee transition: add an operator-approval gate after each committee except the final one.',
    off: 'Remove the operator-approval gates between committees (the ones at committee transitions). Keep any approval gate before the final report.',
  },
  beforeFinal: {
    on: 'Require operator approval before the final report is delivered: add an operator-approval gate after the last committee.',
    off: 'Remove the operator-approval gate before the final report (the one after the last committee).',
  },
}

// Derive switch state from the plan itself — no local mirror to drift out of sync.
// The UI treats committees as sequential (insertion order); the last is terminal.
function deriveSwitches(plan) {
  const names = Object.keys(plan?.committees || {})
  const gateAfter = new Set((plan?.gates || []).map(g => g.after))
  const terminal = names[names.length - 1]
  const nonTerminal = names.slice(0, -1)
  return {
    everyCommittee: nonTerminal.length > 0 && nonTerminal.every(n => gateAfter.has(n)),
    beforeFinal: !!terminal && gateAfter.has(terminal),
  }
}

function BriefSwitchPanel({ plan, disabled, onToggle }) {
  const d = deriveSwitches(plan)
  const rows = [
    { key: 'everyCommittee', label: 'Approve at every committee transition', on: d.everyCommittee, available: true },
    { key: 'beforeFinal', label: 'Approve before the final report', on: d.beforeFinal, available: true },
    { key: 'askRetry', label: 'Ask me before any retry or iterate', on: false, available: false, note: 'requires ensemble support' },
    { key: 'elementGate', label: 'Approve every multi-specialist element', on: false, available: false, note: 'requires harness support' },
  ]
  return (
    <div className="brief-switches">
      <div className="brief-switches-title">
        Operator gates
        {disabled && <span className="brief-switches-spinner">updating…</span>}
      </div>
      {rows.map(r => (
        <div key={r.key} className={`brief-switch${r.available ? '' : ' brief-switch--na'}`}>
          <span className="brief-switch-label">
            {r.label}
            {r.note && <span className="brief-switch-note">{r.note}</span>}
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={r.on}
            disabled={disabled || !r.available}
            onClick={() => onToggle(r.key, !r.on)}
            className={`brief-toggle${r.on ? ' brief-toggle--on' : ''}`}
          >
            <span className="brief-toggle-knob" />
          </button>
        </div>
      ))}
    </div>
  )
}

function PlanPreview({ plan, planReady }) {
  if (!plan) return null
  const committeeNames = Object.keys(plan.committees || {})
  const gates = plan.gates || []
  const terminal = committeeNames[committeeNames.length - 1]

  return (
    <div className="brief-plan-scroll">
      <div style={{ fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', color: '#3b5270', marginBottom: 4 }}>
        Engagement Plan
      </div>
      <div style={{ fontSize: 10, color: '#475569', marginBottom: 18, lineHeight: 1.5 }}>
        {committeeNames.length} committee{committeeNames.length !== 1 ? 's' : ''} will run in sequence.
      </div>

      {!planReady && committeeNames.length > 0 && (
        <div style={{ marginBottom: 18, padding: '10px 14px', background: '#071020', border: '1px solid #1e3050', borderRadius: 6, fontSize: 10, color: '#3b5270' }}>
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

      {/* Terminal gate marker — approval after the last committee, before the report is delivered */}
      {terminal && gates.some(g => g.after === terminal) && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '6px 0' }}>
          <div style={{ width: 1, height: 8, background: '#1e3050' }} />
          <div style={{
            background: '#0d1a2a', border: '1px solid #1e4080', borderRadius: 4,
            padding: '4px 10px', fontSize: 8, color: '#3b82f6',
            letterSpacing: 1.5, textTransform: 'uppercase', fontWeight: 700,
          }}>
            ⬡ Approval before final report
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
  const [panelLocked, setPanelLocked] = useState(false)
  const messagesRef = useRef(null)
  const textareaRef = useRef(null)
  const lockTimer = useRef(null)

  const awaitingReply = dialogMessages.length > 0 && dialogMessages[dialogMessages.length - 1].role === 'orch'

  useEffect(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight
    }
  }, [dialogMessages])

  // A fresh plan (identity changes on every PLAN_READY) releases the switch-panel lock.
  useEffect(() => {
    setPanelLocked(false)
    if (lockTimer.current) { clearTimeout(lockTimer.current); lockTimer.current = null }
  }, [plan])

  useEffect(() => () => { if (lockTimer.current) clearTimeout(lockTimer.current) }, [])

  async function sendMessage(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || sending || proceeding) return
    setSending(true)
    setError(null)
    dispatch({ type: 'DIALOG_OPERATOR_MESSAGE', payload: { text } })
    try {
      await sendChat(engagement.run_id, ORCH, text)
      setInput('')
    } catch (err) {
      setError(err.message)
    } finally {
      setSending(false)
    }
  }

  // Flip a gate switch → send a canned revision to the orchestrator. Lock the whole panel until
  // the revised plan arrives (unlocks in the [plan] effect) or a 3s fallback fires. This
  // serializes gate changes so plan-derived switch state can't race. See BRIEFING.md §5.
  async function handleToggle(key, nextOn) {
    if (panelLocked) return
    const group = SWITCH_MESSAGES[key]
    if (!group) return
    const msg = group[nextOn ? 'on' : 'off']

    setError(null)
    setPanelLocked(true)
    dispatch({ type: 'DIALOG_OPERATOR_MESSAGE', payload: { text: msg } })

    if (lockTimer.current) clearTimeout(lockTimer.current)
    lockTimer.current = setTimeout(() => setPanelLocked(false), 3000)

    try {
      await sendChat(engagement.run_id, ORCH, msg)
    } catch (err) {
      setError(err.message)
      setPanelLocked(false)
      if (lockTimer.current) { clearTimeout(lockTimer.current); lockTimer.current = null }
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

  const planVisible = planReady || plan

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
                placeholder={awaitingReply ? 'Reply to orchestrator…' : 'Message the orchestrator…'}
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

        {/* ── Plan pane ── */}
        <div className="dialog-ext-pane" style={{ display: planVisible ? undefined : 'none' }}>
          <div className="dialog-pane-header">
            <span className="dialog-pane-label">Engagement Plan</span>
          </div>

          <BriefSwitchPanel
            plan={plan}
            disabled={panelLocked || !planReady || proceeding}
            onToggle={handleToggle}
          />

          <PlanPreview plan={plan} planReady={planReady} />

          <div className="brief-action-bar">
            {error && <div className="brief-action-error">{error}</div>}
            <div className="brief-action-buttons">
              <button
                className="plan-review-btn plan-review-btn--reject"
                disabled={proceeding || !planReady}
                onClick={handleRequestChanges}
              >
                Request changes
              </button>
              <button
                className="plan-review-btn plan-review-btn--approve"
                disabled={proceeding || !planReady}
                onClick={handleProceed}
              >
                {proceeding ? 'Starting…' : 'Approve →'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
