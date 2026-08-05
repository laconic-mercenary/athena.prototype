import { useState } from 'react'

// Reusable operator decision widget. Used now for the committee gate (Accept / Redo)
// and designed to be reused for step-level review later (pass showSkip + onSkip).
// The parent supplies the action callbacks (which call the API); this component only
// owns presentation + the Redo-suggestion field. See projects/202607/BRIEFING.md.
export function OperatorDecisionModal({
  title,
  subtitle,
  body,                 // digest / step output to review
  redoAvailable = true, // false when the manifest declares no retry/iterate edge
  onAccept,             // async (selectedChoiceId?) => void
  onRedo,               // async (suggestion: string) => void
  onSkip,               // async () => void  (steps only)
  showSkip = false,
  choices,              // optional [{ id, label, title }] — renders a winner picker (element gate)
  defaultChoiceId,      // the leader's pick, pre-selected in the picker
  onOpenArtifact,
  onClose,
  acceptLabel = 'Accept →',
  redoLabel = 'Redo',
  redoIcon = '↻',
  redoPlaceholder = 'What should change on the redo? (optional)',
  collaboratorEnabled = false,   // show a "@alias" co-approval field on the accept path
  collaboratorPending = null,    // { alias, sentAt } while awaiting a collaborator's co-approval
  collaboratorReply = null,      // { alias, decision, message } — collaborator's latest reply
  collaboratorThread = [],       // [{ role:'operator'|'collaborator', alias?, decision?, message }]
  onSendCollaboratorMessage,     // async (text) => void — email a follow-up to the collaborator
  onCancelCollaboration,         // () => void — abandon the engagement while the thread is open
}) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  const [redoOpen, setRedoOpen] = useState(false)
  const [suggestion, setSuggestion] = useState('')
  const [selected, setSelected] = useState(defaultChoiceId)
  const [collaborator, setCollaborator] = useState('')
  const [collabMsg, setCollabMsg] = useState('')
  const [collabSending, setCollabSending] = useState(false)

  async function sendCollab() {
    const t = collabMsg.trim()
    if (!t || collabSending || !onSendCollaboratorMessage) return
    setCollabSending(true)
    setError(null)
    try {
      await onSendCollaboratorMessage(t)
      setCollabMsg('')
    } catch (err) {
      setError(err.message)
    } finally {
      setCollabSending(false)
    }
  }

  const hasChoices = Array.isArray(choices) && choices.length > 0
  const overriding = hasChoices && selected !== defaultChoiceId

  async function run(fn) {
    if (pending) return
    setPending(true)
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(err.message)
      setPending(false)
    }
  }

  return (
    <div className="chat-overlay" onClick={onClose}>
      <div className="chat-panel chat-panel--review" onClick={e => e.stopPropagation()}>

        <div className="chat-header">
          <div>
            <div className="chat-title">{title}</div>
            {subtitle && <div className="chat-subtitle">{subtitle}</div>}
          </div>
          <button className="chat-close" onClick={onClose}>✕</button>
        </div>

        {hasChoices && (
          <div className="gate-choices" style={{ padding: '10px 16px 2px', display: 'flex', flexDirection: 'column', gap: 6 }}>
            {choices.map(c => {
              const isSel = c.id === selected
              const isLeader = c.id === defaultChoiceId
              return (
                <button
                  type="button"
                  key={c.id}
                  className="gate-choice"
                  onClick={() => setSelected(c.id)}
                  style={{
                    textAlign: 'left', padding: '8px 10px', borderRadius: 6, cursor: 'pointer',
                    border: `1px solid ${isSel ? '#3b82f6' : '#1e293b'}`,
                    background: isSel ? 'rgba(59,130,246,0.10)' : 'transparent',
                    display: 'flex', flexDirection: 'column', gap: 6,
                  }}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{
                      width: 12, height: 12, borderRadius: '50%', flexShrink: 0,
                      border: `2px solid ${isSel ? '#3b82f6' : '#475569'}`,
                      background: isSel ? '#3b82f6' : 'transparent',
                    }} />
                    <span style={{ flex: 1, fontSize: 12, color: '#cbd5e1' }}>
                      <span style={{ fontWeight: 600 }}>{c.label}</span>
                      {c.title && <span style={{ color: '#64748b' }}> · {c.title}</span>}
                    </span>
                    {isLeader && (
                      <span style={{ fontSize: 9, color: '#22c55e', border: '1px solid #22c55e', borderRadius: 4, padding: '1px 5px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                        Leader's pick
                      </span>
                    )}
                  </span>
                  {c.output && (
                    <pre style={{
                      margin: 0, padding: '6px 8px 6px 22px',
                      fontSize: 10, color: '#94a3b8', lineHeight: 1.5,
                      whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'inherit',
                      maxHeight: 120, overflowY: 'auto',
                    }}>
                      {c.output}
                    </pre>
                  )}
                </button>
              )
            })}
          </div>
        )}

        <div className="chat-thread" style={{ flex: 1 }}>
          {body ? (
            <pre style={{
              margin: 0, padding: '12px 16px',
              fontSize: 10, color: '#64748b',
              lineHeight: 1.6, whiteSpace: 'pre-wrap',
              wordBreak: 'break-word', fontFamily: 'inherit',
            }}>
              {body}
            </pre>
          ) : (
            <div className="chat-empty">
              No digest available — open the artifact for full context before deciding.
            </div>
          )}
        </div>

        {redoOpen && (
          <div style={{ padding: '0 16px 4px' }}>
            <textarea
              className="dialog-textarea"
              rows={2}
              placeholder={redoPlaceholder}
              value={suggestion}
              onChange={e => setSuggestion(e.target.value)}
              autoFocus
            />
          </div>
        )}

        {collaboratorReply && collaboratorReply.decision === 'approve' ? (
          <div className="chat-actions plan-review-actions" style={{ padding: '12px 16px', flexDirection: 'column', alignItems: 'flex-start', gap: 6 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 600, color: '#22c55e' }}>
              ✓ @{collaboratorReply.alias} approved
            </span>
            {collaboratorReply.message && (
              <div style={{ fontSize: 12, color: '#94a3b8', whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{collaboratorReply.message}</div>
            )}
          </div>
        ) : collaboratorPending ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '10px 16px 14px' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#a78bfa' }}>
              <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#8b5cf6', boxShadow: '0 0 6px #8b5cf6' }} />
              Thread with @{collaboratorPending.alias} · awaiting <strong style={{ color: '#22c55e' }}>APPROVE</strong>
              {collaboratorPending.sentAt && (
                <span style={{ color: '#64748b' }}>
                  · sent {new Date(collaboratorPending.sentAt).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
                </span>
              )}
            </span>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 200, overflowY: 'auto', padding: '2px 0' }}>
              {collaboratorThread.length === 0 ? (
                <div style={{ fontSize: 11, color: '#64748b', fontStyle: 'italic' }}>
                  Approval request sent — waiting for @{collaboratorPending.alias} to reply. Send a message below to keep the conversation going.
                </div>
              ) : collaboratorThread.map((m, i) => {
                const mine = m.role === 'operator'
                const denied = m.decision === 'deny'
                return (
                  <div key={i} style={{
                    alignSelf: mine ? 'flex-end' : 'flex-start', maxWidth: '85%',
                    background: mine ? 'rgba(59,130,246,0.10)' : 'rgba(139,92,246,0.10)',
                    border: `1px solid ${mine ? 'rgba(59,130,246,0.25)' : 'rgba(139,92,246,0.25)'}`,
                    borderRadius: mine ? '8px 8px 2px 8px' : '8px 8px 8px 2px', padding: '6px 10px',
                  }}>
                    <div style={{ fontSize: 9, letterSpacing: 0.5, textTransform: 'uppercase', marginBottom: 2, display: 'flex', gap: 6, alignItems: 'center', color: mine ? '#3b82f6' : '#a78bfa' }}>
                      {mine ? 'You' : `@${m.alias}`}
                      {denied && <span style={{ color: '#ef4444', border: '1px solid #ef4444', borderRadius: 3, padding: '0 4px', fontSize: 8 }}>denied</span>}
                    </div>
                    <div style={{ fontSize: 12, color: '#cbd5e1', whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                      {m.message || (denied ? '(denied — no message)' : '(no message)')}
                    </div>
                  </div>
                )
              })}
            </div>

            <textarea
              className="dialog-textarea"
              rows={2}
              placeholder={`Message @${collaboratorPending.alias}…`}
              value={collabMsg}
              onChange={e => setCollabMsg(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); sendCollab() } }}
            />
            <div className="chat-actions plan-review-actions" style={{ padding: 0, gap: 8 }}>
              {error && <span className="chat-error">{error}</span>}
              {onCancelCollaboration && (
                <button
                  type="button"
                  className="plan-review-btn plan-review-btn--reject"
                  onClick={onCancelCollaboration}
                >
                  Cancel
                </button>
              )}
              <button
                type="button"
                className="plan-review-btn plan-review-btn--approve"
                disabled={collabSending || !collabMsg.trim()}
                onClick={sendCollab}
              >
                {collabSending ? 'Sending…' : 'Send →'}
              </button>
            </div>
          </div>
        ) : (
        <>
        {collaboratorEnabled && !redoOpen && (
          <div style={{ padding: '0 16px 4px' }}>
            <input
              type="text"
              className="dialog-textarea"
              placeholder="@alias — co-approve this advance (optional)"
              value={collaborator}
              onChange={e => setCollaborator(e.target.value)}
              style={{ width: '100%' }}
            />
          </div>
        )}

        <div className="chat-actions plan-review-actions" style={{ padding: '12px 16px', gap: 8 }}>
          {error && <span className="chat-error">{error}</span>}

          {onOpenArtifact && (
            <button
              type="button"
              className="plan-review-btn"
              style={{ border: '1px solid #334155', color: '#94a3b8', background: 'transparent' }}
              onClick={onOpenArtifact}
            >
              Artifact ↗
            </button>
          )}

          {showSkip && onSkip && (
            <button
              type="button"
              className="plan-review-btn plan-review-btn--reject"
              disabled={pending}
              onClick={() => run(onSkip)}
            >
              Skip
            </button>
          )}

          {redoAvailable && (
            // Picker mode (element gate) takes no suggestion — Redo is one click. The
            // suggestion textarea flow is only for prose-review gates (committee / step).
            hasChoices ? (
              <button
                type="button"
                className="plan-review-btn plan-review-btn--redo"
                disabled={pending}
                onClick={() => run(() => onRedo())}
              >
                {redoLabel} {redoIcon}
              </button>
            ) : redoOpen ? (
              <button
                type="button"
                className="plan-review-btn plan-review-btn--redo"
                disabled={pending}
                onClick={() => run(() => onRedo(suggestion.trim()))}
              >
                {pending ? 'Processing…' : `Confirm ${redoLabel}`}
              </button>
            ) : (
              <button
                type="button"
                className="plan-review-btn plan-review-btn--redo"
                disabled={pending}
                onClick={() => setRedoOpen(true)}
              >
                {redoLabel} {redoIcon}
              </button>
            )
          )}

          <button
            type="button"
            className="plan-review-btn plan-review-btn--approve"
            disabled={pending}
            onClick={() => run(() => onAccept(selected, collaborator.trim()))}
          >
            {pending ? 'Processing…'
              : overriding ? 'Confirm Override →'
              : (collaboratorEnabled && collaborator.trim()) ? 'Co-Approve →'
              : acceptLabel}
          </button>
        </div>
        </>
        )}

      </div>
    </div>
  )
}
