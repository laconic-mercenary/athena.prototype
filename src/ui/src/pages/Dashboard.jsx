import { useState } from 'react'
import { CommitteeGraph } from '../components/CommitteeGraph'
import { SystemView } from '../components/SystemView'
import { ArtifactTable } from '../components/ArtifactTable'
import { OperatorChat } from '../components/OperatorChat'

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

export function Dashboard({ state, dispatch }) {
  const { engagement, committees, agents, chat, latestEvent } = state
  const [graphTab, setGraphTab] = useState('agent')

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1 className="dash-title">Athena</h1>
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
          </div>

          <StatusTicker event={latestEvent} engagementStatus={engagement.status} />

          <div className="graph-canvas">
            {graphTab === 'agent'
              ? <CommitteeGraph state={state} dispatch={dispatch} />
              : <SystemView state={state} dispatch={dispatch} />
            }
          </div>
        </div>

        {graphTab === 'agent' && (
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
    </div>
  )
}
