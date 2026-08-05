import { useState, useRef, useEffect } from 'react'
import { marked } from 'marked'
import { sendChat, planReview, loopGateArm, abortEngagement } from '../api'
import { FeedbackModal, ReportButton } from '../components/FeedbackModal'
import { EngagementInfoModal } from '../components/EngagementInfoModal'
import { Accordion, SpecialistRow, CommitteePanel } from '../components/CommitteeTree'

marked.setOptions({ breaks: true })

const ORCH = 'athena.orchestrator'

// Render the EngagementPlan as a plain-text briefing for the co-approval email
// attachment. A raw JSON blob is unreadable in an inbox; the collaborator wants
// prose. Mirrors the EngagementPlan shape (operator_instructions, committees with
// objective/constraints/emphasis, gates). See src/athena/engagement_plan.py.
function buildPlanBriefing(plan) {
  const rule = '='.repeat(64)
  const sub = '-'.repeat(64)
  const out = ['ATHENA ENGAGEMENT PLAN', rule]
  if (plan.engagement_id) out.push(`Engagement: ${plan.engagement_id}`)
  out.push('')

  if (plan.operator_instructions) {
    out.push('OPERATOR INSTRUCTIONS', sub, plan.operator_instructions.trim(), '')
  }

  const committees = plan.committees || {}
  const names = Object.keys(committees)
  if (names.length) {
    out.push('COMMITTEES', sub)
    for (const name of names) {
      const c = committees[name] || {}
      out.push('', `▸ ${name}`)
      const objective = c.objective || []
      if (objective.length) {
        out.push('  Objectives:')
        objective.forEach((o, i) => out.push(`    ${i + 1}. ${o}`))
      }
      if ((c.constraints || []).length) {
        out.push('  Constraints:')
        c.constraints.forEach(x => out.push(`    - ${x}`))
      }
      if ((c.emphasis || []).length) {
        out.push('  Emphasis:')
        c.emphasis.forEach(x => out.push(`    - ${x}`))
      }
    }
    out.push('')
  }

  const gates = plan.gates || []
  if (gates.length) {
    out.push('APPROVAL GATES', sub)
    gates.forEach(g => out.push(`  - after ${g.after}: ${g.type}`))
    out.push('')
  }

  return out.join('\n')
}

// Fallback for a toggle whose revised plan never arrives (orchestrator answered
// conversationally, was slow, or the response dropped). Long enough not to fire during a
// normal LLM revision round-trip; short enough that the panel never wedges for long.
const PANEL_LOCK_FALLBACK_MS = 12000

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

// Arm-switch state derives from armedGates (any committee armed for that kind), the same
// source of truth the graph-view toggles use — so briefing and engagement stay in sync.
function deriveArmSwitches(armedGates) {
  const vals = Object.values(armedGates || {})
  return {
    preAction: vals.some(g => g.tool),
    postAction: vals.some(g => g.step),
  }
}

// Small "(?)" affordance with a hover tooltip — explains what a gate switch does
// without cluttering the row. Styled to match the dark briefing panel.
function InfoTip({ text }) {
  const [show, setShow] = useState(false)
  return (
    <span
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
      style={{ position: 'relative', display: 'inline-flex', marginLeft: 6, cursor: 'help', verticalAlign: 'middle' }}
    >
      <span style={{
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        width: 13, height: 13, borderRadius: '50%', fontSize: 9, fontWeight: 700,
        border: '1px solid #3b5270', color: '#64748b', lineHeight: 1,
      }}>?</span>
      {show && (
        <span style={{
          position: 'absolute', bottom: 'calc(100% + 6px)', left: '50%', transform: 'translateX(-50%)',
          width: 230, zIndex: 60, background: '#0f172a', border: '1px solid #1e3050',
          borderRadius: 6, padding: '9px 11px', boxShadow: '0 6px 22px rgba(0,0,0,0.7)',
          fontSize: 10, fontWeight: 400, color: '#94a3b8', lineHeight: 1.55,
          textAlign: 'left', whiteSpace: 'normal', textTransform: 'none', letterSpacing: 0,
        }}>{text}</span>
      )}
    </span>
  )
}

function BriefSwitchPanel({ plan, armedGates, disabled, armDisabled, onToggle }) {
  const d = deriveSwitches(plan)
  const a = deriveArmSwitches(armedGates)
  // Two switch families. "plan" switches are operator-approval gates baked into the plan
  // (routed through the orchestrator, panel locks during the round-trip). "arm" switches
  // toggle in-loop operator review at runtime (armed directly, no orchestrator, instant).
  const rows = [
    { key: 'everyCommittee', label: 'Approve at every committee transition', on: d.everyCommittee, kind: 'plan',
      tip: 'Adds an operator-approval gate after each committee except the last. The engagement pauses at every transition until you approve, reject, or request changes. Baked into the plan.' },
    { key: 'beforeFinal', label: 'Approve before the final report', on: d.beforeFinal, kind: 'plan',
      tip: 'Adds an operator-approval gate after the final committee, so you review and approve before the report is delivered. Baked into the plan.' },
    { key: 'preAction', label: 'Operator review — before each action', on: a.preAction, kind: 'arm', note: 'approve or deny each specialist tool call',
      tip: 'Runtime gate: pauses before each specialist tool call so you can approve or deny it. Armed instantly — does not change the plan.' },
    { key: 'postAction', label: 'Operator review — after each step', on: a.postAction, kind: 'arm', note: 'accept, redo, or skip each step',
      tip: 'Runtime gate: pauses after each committee step so you can accept it, request a redo, or skip it. Armed instantly — does not change the plan.' },
  ]
  return (
    <div className="brief-switches">
      <div className="brief-switches-title">
        Operator gates
        {disabled && <span className="brief-switches-spinner">updating…</span>}
      </div>
      {rows.map(r => {
        const rowDisabled = r.kind === 'plan' ? disabled : armDisabled
        return (
          <div key={r.key} className="brief-switch">
            <span className="brief-switch-label">
              <span>
                {r.label}
                {r.tip && <InfoTip text={r.tip} />}
              </span>
              {r.note && <span className="brief-switch-note">{r.note}</span>}
            </span>
            <button
              type="button"
              role="switch"
              aria-checked={r.on}
              disabled={rowDisabled}
              onClick={() => onToggle(r.key, !r.on)}
              className={`brief-toggle${r.on ? ' brief-toggle--on' : ''}`}
            >
              <span className="brief-toggle-knob" />
            </button>
          </div>
        )
      })}
    </div>
  )
}

// ── Plan tree ─────────────────────────────────────────────────────────────────
function PlanTree({ plan, planReady, manifestSummary, disabledSpecialists, runId, onToggleSpecialist }) {
  if (!plan && !manifestSummary) return null

  const gates = plan?.gates || []
  const terminal = manifestSummary
    ? manifestSummary.committees[manifestSummary.committees.length - 1]?.name
    : Object.keys(plan?.committees || {}).slice(-1)[0]

  // Merge plan objectives with manifest structure. Manifest is the authority on
  // committees/elements/specialists; plan provides objectives per committee.
  const committees = manifestSummary
    ? manifestSummary.committees
    : Object.keys(plan?.committees || {}).map(name => ({ name, elements: [] }))

  return (
    <div className="brief-plan-scroll">
      <div style={{ fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', color: '#3b5270', marginBottom: 4 }}>
        Engagement Plan
      </div>

      {!planReady && plan && (
        <div style={{ marginBottom: 14, padding: '8px 12px', background: '#071020', border: '1px solid #1e3050', borderRadius: 6, fontSize: 10, color: '#3b5270' }}>
          Orchestrator is revising the plan…
        </div>
      )}

      {committees.map((committee, i) => {
        const name = committee.name
        const brief = plan?.committees?.[name] || {}
        const objectives = brief.objective || []
        const gate = gates.find(g => g.after === name)
        const isLast = i === committees.length - 1

        return (
          <div key={name}>
            {/* Committee card */}
            <div style={{ background: '#0a121e', border: '1px solid #1e3050', borderRadius: 6, padding: '10px 12px', marginBottom: 0 }}>
              {/* Header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <span style={{
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  width: 16, height: 16, borderRadius: '50%', background: '#1e3050',
                  color: '#64748b', fontSize: 9, fontWeight: 700, flexShrink: 0,
                }}>{i + 1}</span>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', letterSpacing: 0.5, textTransform: 'uppercase' }}>
                  {name}
                </span>
              </div>

              <CommitteePanel
                committee={committee}
                objectives={objectives}
                disabledSpecialists={disabledSpecialists}
                onToggleSpecialist={(key, enabled) => onToggleSpecialist(runId, key, enabled)}
              />
            </div>

            {/* Gate / connector between committees */}
            {!isLast && (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '6px 0' }}>
                {gate ? (
                  <>
                    <div style={{ width: 1, height: 8, background: '#1e3050' }} />
                    <div style={{
                      background: '#0d1a2a', border: '1px solid #1e4080', borderRadius: 4,
                      padding: '4px 10px', fontSize: 8, color: '#3b82f6',
                      letterSpacing: 1.5, textTransform: 'uppercase', fontWeight: 700,
                    }}>⬡ Operator approval required</div>
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

      {terminal && gates.some(g => g.after === terminal) && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '6px 0' }}>
          <div style={{ width: 1, height: 8, background: '#1e3050' }} />
          <div style={{
            background: '#0d1a2a', border: '1px solid #1e4080', borderRadius: 4,
            padding: '4px 10px', fontSize: 8, color: '#3b82f6',
            letterSpacing: 1.5, textTransform: 'uppercase', fontWeight: 700,
          }}>⬡ Approval before final report</div>
        </div>
      )}
    </div>
  )
}

export function OrchestratorDialog({ state, dispatch, onToggleSpecialist }) {
  const { engagement, dialogMessages, planReady, plan, armedGates, collaboratorPending, manifestSummary, disabledSpecialists } = state

  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [proceeding, setProceeding] = useState(false)
  const [collaboratorAlias, setCollaboratorAlias] = useState('')
  const [error, setError] = useState(null)
  const [panelLocked, setPanelLocked] = useState(false)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [infoOpen, setInfoOpen] = useState(false)
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

  // Flip a gate switch → send a canned revision to the orchestrator. Lock the whole panel
  // until the revised plan arrives (unlocks in the [plan] effect) or the fallback fires.
  // The fallback restores BOTH the local lock and planReady — clearing panelLocked alone
  // isn't enough, because PLAN_REVISION set planReady=false and the panel is also disabled
  // on !planReady. This serializes gate changes so plan-derived state can't race. BRIEFING.md §5.
  async function handleToggle(key, nextOn) {
    // Arm switches (pre/post-action) toggle in-loop review at runtime — armed directly on
    // every committee, no orchestrator round-trip, so they never lock the panel.
    if (key === 'preAction' || key === 'postAction') {
      const gateKind = key === 'preAction' ? 'tool' : 'step'
      setError(null)
      try {
        for (const name of Object.keys(plan?.committees || {})) {
          await loopGateArm(engagement.run_id, name, gateKind, nextOn)
          dispatch({ type: 'GATE_ARMED', payload: { committee: name, kind: gateKind, armed: nextOn } })
        }
      } catch (err) {
        setError(err.message)
      }
      return
    }

    if (panelLocked) return
    const group = SWITCH_MESSAGES[key]
    if (!group) return
    const msg = group[nextOn ? 'on' : 'off']

    setError(null)
    setPanelLocked(true)
    dispatch({ type: 'DIALOG_OPERATOR_MESSAGE', payload: { text: msg } })

    if (lockTimer.current) clearTimeout(lockTimer.current)
    lockTimer.current = setTimeout(() => {
      setPanelLocked(false)
      dispatch({ type: 'PLAN_REVISION_TIMEOUT' })
    }, PANEL_LOCK_FALLBACK_MS)

    try {
      await sendChat(engagement.run_id, ORCH, msg)
    } catch (err) {
      setError(err.message)
      setPanelLocked(false)
      dispatch({ type: 'PLAN_REVISION_TIMEOUT' })
      if (lockTimer.current) { clearTimeout(lockTimer.current); lockTimer.current = null }
    }
  }

  function handleRequestChanges() {
    setInput(prev => 'I want to make changes to the plan.\n\n' + prev)
    setTimeout(() => textareaRef.current?.focus(), 0)
  }

  async function handleProceed() {
    if (!planReady || proceeding || collaboratorPending) return
    setProceeding(true)
    setError(null)
    try {
      const alias = collaboratorAlias.trim() || null
      const planText = alias && plan ? buildPlanBriefing(plan) : null
      const resp = await planReview(engagement.run_id, 'approve', alias, planText)
      if (resp.action !== 'collaborator_pending') {
        dispatch({ type: 'NAVIGATE', payload: 'dashboard' })
      }
      // Collaboration path: SSE engagement.collaborator_pending drives UI,
      // SSE engagement.approved drives navigation — nothing more to do here.
    } catch (err) {
      setError(err.message)
    } finally {
      setProceeding(false)
    }
  }

  async function handleRestart() {
    if (engagement.run_id) {
      // Best-effort: even if the abort call fails, we still reset the UI to the start
      // screen — but never swallow the failure silently.
      try {
        await abortEngagement(engagement.run_id)
      } catch (err) {
        console.warn('restart: abort request failed, resetting UI anyway', err)
      }
    }
    dispatch({ type: 'RESET' })
  }

  const planVisible = planReady || plan || manifestSummary

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
        <button
          className="dash-info-btn"
          onClick={() => setInfoOpen(true)}
          title="Engagement info"
        >
          ⓘ Info
        </button>
        <button
          className="dash-restart-btn"
          onClick={handleRestart}
          title="Kill switch — halt the harness threads and abandon this engagement"
        >
          ⏻ KILL SWITCH
        </button>
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
              const isCollab = msg.role === 'collab'
              const roleName = isOrch ? 'Orchestrator' : isCollab ? `@${msg.alias} · collaborator` : 'Operator'
              return (
                <div key={i} className={`dialog-msg dialog-msg--${isOrch ? 'orch' : msg.role}`}>
                  <div className="dialog-msg-meta">
                    <span
                      className={`dialog-msg-role dialog-msg-role--${isOrch ? 'orch' : msg.role}`}
                      style={isCollab ? { color: '#a78bfa' } : undefined}
                    >
                      {roleName}
                    </span>
                    <span className="dialog-msg-time">
                      {new Date(msg.ts).toLocaleTimeString('en-GB', {
                        hour: '2-digit', minute: '2-digit', second: '2-digit',
                      })}
                    </span>
                    {isOrch && <ReportButton onClick={() => setFeedbackOpen(true)} />}
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
            armedGates={armedGates}
            disabled={panelLocked || !planReady || proceeding}
            armDisabled={!planReady || proceeding || !engagement.run_id}
            onToggle={handleToggle}
          />

          <PlanTree
            plan={plan}
            planReady={planReady}
            manifestSummary={manifestSummary}
            disabledSpecialists={disabledSpecialists || {}}
            runId={engagement.run_id}
            onToggleSpecialist={onToggleSpecialist}
          />

          <div className="brief-action-bar">
            {error && <div className="brief-action-error">{error}</div>}
            {collaboratorPending ? (
              <div className="brief-collab-pending">
                <span className="brief-collab-pending-dot" />
                Awaiting @{collaboratorPending.alias}
                <span className="brief-collab-pending-time">
                  · sent {new Date(collaboratorPending.sentAt).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
            ) : (
              <>
                <div className="brief-collab-row">
                  <input
                    className="brief-collab-input"
                    type="text"
                    placeholder="@alias — request co-approval (optional)"
                    value={collaboratorAlias}
                    onChange={e => setCollaboratorAlias(e.target.value)}
                    disabled={proceeding || !planReady}
                  />
                </div>
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
                    {proceeding ? 'Sending…' : collaboratorAlias.trim() ? 'Co-Approve →' : 'Approve →'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      <FeedbackModal open={feedbackOpen} onClose={() => setFeedbackOpen(false)} />

      {infoOpen && (
        <EngagementInfoModal
          engagement={engagement}
          phase="Briefing"
          committeeCount={Object.keys(state.committees).length || undefined}
          onClose={() => setInfoOpen(false)}
        />
      )}
    </div>
  )
}
