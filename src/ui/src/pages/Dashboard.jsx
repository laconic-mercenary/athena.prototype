import { CommitteeGraph } from '../components/CommitteeGraph'
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

export function Dashboard({ state, dispatch }) {
  const { engagement, committees, agents, chat } = state

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
          <CommitteeGraph state={state} dispatch={dispatch} />
        </div>
        <div className="side-pane">
          <ArtifactTable
            runId={engagement.run_id}
            committees={committees}
          />
        </div>
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
