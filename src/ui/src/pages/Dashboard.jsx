import { useMemo, useState } from 'react'
import { CommitteeGraph } from '../components/CommitteeGraph'
import { SystemView } from '../components/SystemView'
import { ArtifactTable } from '../components/ArtifactTable'
import { OperatorChat } from '../components/OperatorChat'
import { OperatorDecisionModal } from '../components/OperatorDecisionModal'
import { ReportChat } from '../components/ReportChat'
import { ReportModal } from '../components/ReportModal'
import { CommitteeResultsModal } from '../components/CommitteeResultsModal'
import { formatToolSummary } from '../App'
import { gateDecision } from '../api'

const COMMITTEE_PALETTE = ['#f97316', '#22c55e', '#ef4444', '#eab308', '#3b82f6', '#a855f7', '#06b6d4']
function committeeColor(name, committeeNames) {
  if (name === 'orchestrator') return '#e2e8f0'
  const idx = committeeNames.indexOf(name)
  return COMMITTEE_PALETTE[idx % COMMITTEE_PALETTE.length] || '#94a3b8'
}

const STATUS_LABEL = {
  idle: 'Idle', running: 'Running', completed: 'Completed', rejected: 'Rejected', failed: 'Failed',
}
const STATUS_COLOR = {
  idle: '#64748b', running: '#22c55e', completed: '#e2e8f0', rejected: '#ef4444', failed: '#ef4444',
}
const EVENT_COLOR = {
  tool: '#64748b', spawned: '#22c55e', finding: null, committee: '#94a3b8', done: '#e2e8f0', gate: null,
}
const FINDING_COLOR = {
  signal_critical: '#ef4444', signal_warn: '#f97316', signal_info: '#3b82f6',
}
const GATE_COLORS = { advance: '#22c55e', retry: '#ef4444', iterate: '#f97316' }

function fmtTime(ts) {
  return new Date(ts).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function SystemLogPanel({ eventLog }) {
  const entries = [...(eventLog || [])].reverse()
  return (
    <div style={{ height: '100%', overflowY: 'auto', padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 3 }}>
      {entries.length === 0 && (
        <div style={{ fontSize: 11, color: '#1e3050' }}>No events yet</div>
      )}
      {entries.map((entry, i) => (
        <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'baseline', fontSize: 11 }}>
          <span style={{ color: '#2d4060', flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>
            {fmtTime(entry.ts)}
          </span>
          <span style={{ color: entry.color || '#475569', lineHeight: 1.5 }}>{entry.text}</span>
        </div>
      ))}
    </div>
  )
}

const TEXT_PREVIEW_MAX = 400

function AgentLogPanel({ agents, committeeNames }) {
  // Match the System Log's newest-first ordering: float the most-recently-active
  // agent to the top, and show each agent's latest message at the top of its block.
  const agentList = Object.values(agents)
    .map(agent => {
      const log = agent.messageLog || []
      return { agent, lastTs: log.length ? log[log.length - 1].ts : 0 }
    })
    .sort((a, b) => b.lastTs - a.lastTs)
  return (
    <div style={{ height: '100%', overflowY: 'auto', padding: '12px 16px' }}>
      {agentList.length === 0 && (
        <div style={{ fontSize: 11, color: '#1e3050' }}>No agents yet</div>
      )}
      {agentList.map(({ agent }) => {
        const log = [...(agent.messageLog || [])].reverse()
        const color = committeeColor(agent.committee, committeeNames)
        return (
          <div key={agent.id} style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
              <span style={{
                fontSize: 8, letterSpacing: 1.5, textTransform: 'uppercase',
                color: `${color}99`, background: `${color}12`,
                border: `1px solid ${color}33`, borderRadius: 3, padding: '1px 6px',
              }}>
                {agent.committee}
              </span>
              <span style={{ fontSize: 11, fontWeight: 600, color: `${color}cc` }}>
                {agent.title || agent.id.split('.').pop()}
              </span>
              <span style={{ fontSize: 9, color: agent.status === 'active' ? '#22c55e' : '#2d4060' }}>
                {agent.status}
              </span>
            </div>
            {log.length === 0 ? (
              <div style={{ fontSize: 10, color: '#1e3050', paddingLeft: 8 }}>no messages</div>
            ) : log.map((entry, i) => (
              entry.kind === 'tool' ? (
                <div key={i} style={{ display: 'flex', gap: 10, fontSize: 10, alignItems: 'baseline', paddingLeft: 8, marginBottom: 2 }}>
                  <span style={{ color: '#2d4060', flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>
                    {fmtTime(entry.ts)}
                  </span>
                  <span style={{ color: '#64748b' }}>
                    ⚙ {formatToolSummary(entry.tool, entry.input_summary)}
                  </span>
                </div>
              ) : entry.kind === 'operator' ? (
                <div key={i} style={{ display: 'flex', gap: 10, fontSize: 10, alignItems: 'flex-start', paddingLeft: 8, marginBottom: 4 }}>
                  <span style={{ color: '#2d4060', flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>
                    {fmtTime(entry.ts)}
                  </span>
                  <span style={{ color: '#3b82f6', lineHeight: 1.5 }}>
                    <span style={{ fontWeight: 700, letterSpacing: 0.5 }}>operator › </span>
                    {entry.text.length > TEXT_PREVIEW_MAX ? entry.text.slice(0, TEXT_PREVIEW_MAX) + '…' : entry.text}
                  </span>
                </div>
              ) : (
                <div key={i} style={{ display: 'flex', gap: 10, fontSize: 10, alignItems: 'flex-start', paddingLeft: 8, marginBottom: 4 }}>
                  <span style={{ color: '#2d4060', flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>
                    {fmtTime(entry.ts)}
                  </span>
                  <span style={{
                    color: entry.stop_reason === 'end_turn' ? '#94a3b8' : '#475569',
                    fontStyle: 'italic', lineHeight: 1.5,
                  }}>
                    {entry.text.length > TEXT_PREVIEW_MAX
                      ? entry.text.slice(0, TEXT_PREVIEW_MAX) + '…'
                      : entry.text}
                  </span>
                </div>
              )
            ))}
          </div>
        )
      })}
    </div>
  )
}

function StatusTicker({ event, latestGateDecision, engagementStatus }) {
  const isRunning = engagementStatus === 'running'

  if (!event) {
    return (
      <div className="status-ticker">
        <span className="ticker-dot" style={{ background: isRunning ? '#22c55e' : '#1e293b' }} />
        <span className="ticker-text" style={{ color: '#1e3050' }}>
          {isRunning ? 'initialising…' : 'no activity'}
        </span>
      </div>
    )
  }

  let color, dotColor
  if (event.kind === 'gate') {
    color = event.color || '#94a3b8'
    dotColor = color
  } else if (event.kind === 'finding') {
    color = FINDING_COLOR[event.classification] || '#64748b'
    dotColor = isRunning ? '#22c55e' : '#334155'
  } else {
    color = EVENT_COLOR[event.kind] || '#64748b'
    dotColor = isRunning ? '#22c55e' : (event.kind === 'done' ? '#e2e8f0' : '#334155')
  }

  return (
    <div className="status-ticker">
      <span
        className="ticker-dot"
        style={{
          background: dotColor,
          boxShadow: isRunning ? `0 0 5px ${dotColor}` : 'none',
          animation: isRunning ? 'ticker-pulse 2s ease-in-out infinite' : 'none',
        }}
      />
      <span className="ticker-text" style={{ color }}>
        {event.text}
      </span>
    </div>
  )
}

const COMMITTEE_ORDER_FROM_STATE = (committees) => Object.keys(committees)

export function Dashboard({ state, dispatch }) {
  const { engagement, committees, agents, chat, latestEvent, latestGateDecision } = state
  const [graphTab, setGraphTab] = useState('agent')
  const [showArtifacts, setShowArtifacts] = useState(false)
  const [openReport, setOpenReport] = useState(null)
  const [openResults, setOpenResults] = useState(null) // { name, color }
  const [planReviewOpen, setPlanReviewOpen] = useState(false)
  const [reportChatOpen, setReportChatOpen] = useState(false)

  // Highest-severity committee needing operator attention
  const attention = useMemo(() => {
    const committeeNames = Object.keys(committees)
    for (const sev of ['signal_critical', 'signal_warn']) {
      for (const c of committeeNames) {
        if (committees[c]?.classification === sev) {
          const leaderId = Object.keys(agents).find(
            id => agents[id].committee === c && id.endsWith('.leader')
          )
          return {
            committee: c,
            sev,
            leaderId,
            leaderTitle: (leaderId && agents[leaderId]?.title) || `${c} lead`,
            findings: (leaderId && agents[leaderId]?.findings) || committees[c]?.findings || [],
            count: (committees[c]?.findings || []).length,
          }
        }
      }
    }
    return null
  }, [committees, agents])

  // Pending leader questions across all committees
  const pendingLeaderQuestion = useMemo(() => {
    for (const [committee, q] of Object.entries(state.pendingLeaderQuestions || {})) {
      if (q) {
        const leaderId = Object.keys(agents).find(
          id => agents[id].committee === committee && id.endsWith('.leader')
        )
        return {
          committee,
          question: q.question,
          leaderId,
          leaderTitle: (leaderId && agents[leaderId]?.title) || `${committee} lead`,
          findings: (leaderId && agents[leaderId]?.findings) || [],
        }
      }
    }
    return null
  }, [state.pendingLeaderQuestions, agents])

  function openLeadChat(target) {
    dispatch({
      type: 'OPEN_CHAT',
      payload: {
        agentId: target.leaderId,
        committeeId: target.committee,
        agentTitle: target.leaderTitle,
        findings: target.findings,
        focusFindings: !target.question,
      },
    })
  }

  const isCompleted = engagement.status === 'completed'

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1 className="dash-title">Athena</h1>

        {/* Alert hierarchy: approval gate > pending question (orchestrator/leader) > critical finding.
            Short chips — the action, not a sentence; committee shown as a subtle tag. */}
        {engagement.awaitingApproval ? (
          <button
            className="dash-alert-btn dash-alert-btn--approval"
            onClick={() => setPlanReviewOpen(true)}
          >
            ⬢ Approval Required
            {engagement.awaitingCommittee && <span className="dash-alert-tag"> · {engagement.awaitingCommittee}</span>}
          </button>
        ) : state.pendingOrchestratorQuestion && !chat.isOpen ? (
          <button
            className="dash-alert-btn dash-alert-btn--warn"
            onClick={() => dispatch({ type: 'OPEN_CHAT', payload: { agentId: 'athena.orchestrator', committeeId: null, agentTitle: 'Orchestrator', findings: [] } })}
          >
            ✎ Answer Required<span className="dash-alert-tag"> · orchestrator</span>
          </button>
        ) : pendingLeaderQuestion && !chat.isOpen ? (
          <button
            className="dash-alert-btn dash-alert-btn--warn"
            onClick={() => openLeadChat(pendingLeaderQuestion)}
          >
            ✎ Answer Required<span className="dash-alert-tag"> · {pendingLeaderQuestion.committee}</span>
          </button>
        ) : attention && !chat.isOpen ? (
          <button
            className={`dash-alert-btn dash-alert-btn--${attention.sev === 'signal_critical' ? 'crit' : 'warn'}`}
            onClick={() => openLeadChat(attention)}
          >
            ⚠ {attention.sev === 'signal_critical' ? 'Critical' : 'Flagged'}
            {attention.count > 1 ? ` ×${attention.count}` : ''}
            <span className="dash-alert-tag"> · {attention.committee}</span>
          </button>
        ) : null}

        <div className="dash-meta">
          <span className="dash-status" style={{ color: STATUS_COLOR[engagement.status] }}>
            {STATUS_LABEL[engagement.status] || engagement.status}
          </span>
          <span className="dash-run-id">{engagement.run_id}</span>
        </div>
      </header>

      <div className="dashboard-body">
        <div className="graph-pane">
          <div className="graph-tab-bar">
            <button
              className={`graph-tab${graphTab === 'agent' ? ' graph-tab--active' : ''}`}
              onClick={() => setGraphTab('agent')}
            >
              Agent Graph
            </button>
            <button
              className={`graph-tab${graphTab === 'system' ? ' graph-tab--active' : ''}`}
              onClick={() => setGraphTab('system')}
            >
              System View
            </button>
            <button
              className={`graph-tab${graphTab === 'syslog' ? ' graph-tab--active' : ''}`}
              onClick={() => setGraphTab('syslog')}
            >
              System Log
            </button>
            <button
              className={`graph-tab${graphTab === 'agentlog' ? ' graph-tab--active' : ''}`}
              onClick={() => setGraphTab('agentlog')}
            >
              Agent Log
            </button>

            <div className="graph-actions">
              {isCompleted && (
                <button
                  className="dash-action-btn"
                  style={{ borderColor: '#3b82f6', color: '#3b82f6' }}
                  onClick={() => setReportChatOpen(true)}
                >
                  Discuss
                </button>
              )}
              {(graphTab === 'agent' || graphTab === 'system') && (
                <button
                  className={`dash-action-btn${showArtifacts ? ' dash-action-btn--on' : ''}`}
                  onClick={() => setShowArtifacts(v => !v)}
                >
                  {showArtifacts ? 'Hide Artifacts' : 'View Artifacts'}
                </button>
              )}
            </div>
          </div>

          <StatusTicker
            event={latestEvent}
            latestGateDecision={latestGateDecision}
            engagementStatus={engagement.status}
          />

          <div className="graph-canvas">
            {graphTab === 'agent' && (
              <CommitteeGraph
                state={state}
                dispatch={dispatch}
                onCommitteeResults={name => {
                  const color = ['#f97316', '#22c55e', '#ef4444', '#eab308', '#3b82f6', '#a855f7', '#06b6d4']
                  const idx = Object.keys(committees).indexOf(name)
                  setOpenResults({ name, color: color[idx % color.length] || '#94a3b8' })
                }}
              />
            )}
            {graphTab === 'system' && <SystemView state={state} dispatch={dispatch} />}
            {graphTab === 'syslog' && <SystemLogPanel eventLog={state.eventLog} />}
            {graphTab === 'agentlog' && <AgentLogPanel agents={agents} committeeNames={Object.keys(committees)} />}
          </div>

          <div className="graph-footer">
            <span className="graph-footer-label">Looking for other ways to make Athena more capable?</span>
            <a href="/marketplace.html" target="_blank" rel="noopener noreferrer" className="graph-footer-btn">
              View Marketplace
            </a>
          </div>
        </div>

        {graphTab === 'agent' && showArtifacts && (
          <div className="side-pane">
            <ArtifactTable runId={engagement.run_id} committees={committees} />
          </div>
        )}
      </div>

      {reportChatOpen && (
        <ReportChat runId={engagement.run_id} onClose={() => setReportChatOpen(false)} />
      )}

      {planReviewOpen && engagement.awaitingApproval && (
        <OperatorDecisionModal
          title={`${engagement.awaitingCommittee || 'Gate'} · Review`}
          subtitle="Accept to advance, or Redo to re-run this committee"
          body={committees[engagement.awaitingCommittee]?.digest}
          redoAvailable={engagement.awaitingRedoAvailable}
          onAccept={async () => {
            await gateDecision(engagement.run_id, 'accept')
            setPlanReviewOpen(false)
            dispatch({ type: 'GATE_RESOLVED', payload: {} })
          }}
          onRedo={async (suggestion) => {
            await gateDecision(engagement.run_id, 'redo', suggestion)
            setPlanReviewOpen(false)
            dispatch({ type: 'GATE_RESOLVED', payload: {} })
          }}
          onOpenArtifact={engagement.awaitingCommittee ? () => {
            setOpenReport({
              name: engagement.awaitingCommittee,
              title: `${engagement.awaitingCommittee} artifact`,
              accent: '#94a3b8',
            })
          } : undefined}
          onClose={() => setPlanReviewOpen(false)}
        />
      )}

      {chat.isOpen && (
        <OperatorChat
          runId={engagement.run_id}
          agentId={chat.agentId}
          committeeId={chat.committeeId}
          agentTitle={chat.agentTitle}
          findings={chat.findings}
          focusFindings={chat.focusFindings}
          agentReplies={state.agentReplies?.[chat.agentId] || []}
          operatorMessages={(state.agents[chat.agentId]?.messageLog || []).filter(e => e.kind === 'operator')}
          dispatch={dispatch}
          onClose={() => dispatch({ type: 'CLOSE_CHAT' })}
        />
      )}

      {openReport && (
        <ReportModal
          runId={engagement.run_id}
          name={openReport.name}
          title={openReport.title}
          accent={openReport.accent}
          incomplete={committees[openReport.name]?.incomplete}
          onClose={() => setOpenReport(null)}
        />
      )}

      {openResults && (
        <CommitteeResultsModal
          runId={engagement.run_id}
          name={openResults.name}
          color={openResults.color}
          digest={committees[openResults.name]?.digest}
          incomplete={committees[openResults.name]?.incomplete}
          onClose={() => setOpenResults(null)}
          onDiscuss={isCompleted
            ? () => setReportChatOpen(true)
            : () => dispatch({
                type: 'OPEN_CHAT',
                payload: {
                  agentId: 'athena.orchestrator',
                  committeeId: null,
                  agentTitle: 'Orchestrator',
                  findings: [],
                },
              })
          }
        />
      )}
    </div>
  )
}
