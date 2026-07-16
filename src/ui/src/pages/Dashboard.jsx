import { useMemo, useState } from 'react'
import { CommitteeGraph } from '../components/CommitteeGraph'
import { SystemView } from '../components/SystemView'
import { ArtifactTable } from '../components/ArtifactTable'
import { OperatorChat } from '../components/OperatorChat'
import { ReportModal } from '../components/ReportModal'

// Report buttons: which committee's artifact_emitted unlocks them, the .md
// artifact name to fetch, and the accent colour for the modal header.
const REPORTS = [
  { committee: 'planning',  name: 'plan',   label: 'View Planning Report',   title: 'Planning Report',   accent: '#22c55e' },
  { committee: 'reporting', name: 'report', label: 'View Engagement Report', title: 'Engagement Report', accent: '#eab308' },
]

const STATUS_LABEL = {
  idle:      'Idle',
  running:   'Running',
  completed: 'Completed',
  rejected:  'Rejected',
  failed:    'Failed',
}

const STATUS_COLOR = {
  idle:      '#64748b',
  running:   '#22c55e',
  completed: '#e2e8f0',
  rejected:  '#ef4444',
  failed:    '#ef4444',
}

const EVENT_COLOR = {
  tool:      '#64748b',
  spawned:   '#22c55e',
  finding:   null,        // uses classification color below
  committee: '#94a3b8',
  done:      '#e2e8f0',
}

const FINDING_COLOR = {
  signal_critical: '#ef4444',
  signal_warn:     '#f97316',
  signal_info:     '#3b82f6',
}

function StatusTicker({ event, engagementStatus }) {
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

  const color = event.kind === 'finding'
    ? (FINDING_COLOR[event.classification] || '#64748b')
    : (EVENT_COLOR[event.kind] || '#64748b')

  const dotColor = isRunning ? '#22c55e' : (event.kind === 'done' ? '#e2e8f0' : '#334155')

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

const COMMITTEE_ORDER = ['recon', 'planning', 'retrieval', 'reporting']

export function Dashboard({ state, dispatch }) {
  const { engagement, committees, agents, chat, latestEvent } = state
  const [graphTab, setGraphTab] = useState('agent')
  const [showArtifacts, setShowArtifacts] = useState(false)
  const [openReport, setOpenReport] = useState(null)

  // Highest-severity committee currently needing operator attention. Drives the
  // header alert button — a guaranteed-clickable path to brief the lead about a
  // critical finding, independent of the graph's click handling.
  const attention = useMemo(() => {
    for (const sev of ['signal_critical', 'signal_warn']) {
      for (const c of COMMITTEE_ORDER) {
        if (committees[c]?.classification === sev) {
          const leaderId = `athena.${c}.leader`
          return {
            committee: c,
            sev,
            leaderId,
            leaderTitle: agents[leaderId]?.title || `${c} lead`,
            findings: agents[leaderId]?.findings || committees[c]?.findings || [],
            count: (committees[c]?.findings || []).length,
          }
        }
      }
    }
    return null
  }, [committees, agents])

  const openLeadChat = (a) => dispatch({
    type: 'OPEN_CHAT',
    payload: { agentId: a.leaderId, agentTitle: a.leaderTitle, findings: a.findings, focusFindings: true },
  })

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1 className="dash-title">Athena</h1>
        {attention && !chat.isOpen && (
          <button
            className={`dash-alert-btn dash-alert-btn--${attention.sev === 'signal_critical' ? 'crit' : 'warn'}`}
            onClick={() => openLeadChat(attention)}
          >
            {attention.sev === 'signal_critical' ? '⚠ Critical finding' : '⚠ Finding flagged'}
            {attention.count > 1 ? ` ×${attention.count}` : ''} — brief the {attention.committee} lead →
          </button>
        )}
        <div className="dash-meta">
          {engagement.target && (
            <span className="dash-target">{engagement.target}</span>
          )}
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

            <div className="graph-actions">
              {REPORTS.map(r =>
                committees[r.committee]?.artifactReady && (
                  <button
                    key={r.name}
                    className="dash-action-btn"
                    style={{ borderColor: r.accent, color: r.accent }}
                    onClick={() => setOpenReport(r)}
                  >
                    {r.label}
                  </button>
                )
              )}
              {graphTab === 'agent' && (
                <button
                  className={`dash-action-btn${showArtifacts ? ' dash-action-btn--on' : ''}`}
                  onClick={() => setShowArtifacts(v => !v)}
                >
                  {showArtifacts ? 'Hide Artifacts' : 'View Artifacts'}
                </button>
              )}
            </div>
          </div>

          <StatusTicker event={latestEvent} engagementStatus={engagement.status} />

          <div className="graph-canvas">
            {graphTab === 'agent'
              ? <CommitteeGraph state={state} dispatch={dispatch} />
              : <SystemView state={state} dispatch={dispatch} />
            }
          </div>
        </div>

        {graphTab === 'agent' && showArtifacts && (
          <div className="side-pane">
            <ArtifactTable
              runId={engagement.run_id}
              committees={committees}
            />
          </div>
        )}
      </div>

      {chat.isOpen && (
        <OperatorChat
          runId={engagement.run_id}
          agentId={chat.agentId}
          agentTitle={chat.agentTitle}
          findings={chat.findings}
          focusFindings={chat.focusFindings}
          onClose={() => dispatch({ type: 'CLOSE_CHAT' })}
        />
      )}

      {openReport && (
        <ReportModal
          runId={engagement.run_id}
          name={openReport.name}
          title={openReport.title}
          accent={openReport.accent}
          onClose={() => setOpenReport(null)}
        />
      )}
    </div>
  )
}
