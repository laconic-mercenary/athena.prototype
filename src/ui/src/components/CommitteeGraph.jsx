import { useMemo } from 'react'
import {
  ReactFlow,
  Background,
  Handle,
  Position,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

const COMMITTEE_COLORS = {
  orchestrator: '#e2e8f0',
  recon:        '#f97316',
  planning:     '#22c55e',
  retrieval:    '#ef4444',
  reporting:    '#eab308',
}

function classificationColor(cls) {
  if (cls === 'signal_critical') return '#ef4444'
  if (cls === 'signal_warn')     return '#f97316'
  return null
}

// ── Committee node ──────────────────────────────────────────────────
function CommitteeNode({ data }) {
  const { label, committee, status, classification, badgeCount, onClick } = data
  const color     = COMMITTEE_COLORS[committee] || '#94a3b8'
  const alertColor = classificationColor(classification)
  const isActive   = status === 'active'
  const isDone     = status === 'completed'

  return (
    <div
      onClick={onClick}
      style={{
        background: '#0f172a',
        border: `2px solid ${alertColor || color}`,
        borderRadius: 8,
        padding: '12px 22px',
        color,
        fontWeight: 700,
        fontSize: 13,
        minWidth: 160,
        textAlign: 'center',
        cursor: badgeCount > 0 ? 'pointer' : 'default',
        boxShadow: isActive ? `0 0 16px 4px ${color}55` : 'none',
        opacity: isDone ? 0.7 : 1,
        transition: 'box-shadow 0.4s, border-color 0.3s',
        position: 'relative',
        userSelect: 'none',
      }}
    >
      <Handle type="target" position={Position.Top}    style={{ visibility: 'hidden' }} />

      <div style={{ letterSpacing: 1 }}>{label}</div>

      {status !== 'inactive' && (
        <div style={{
          fontSize: 9,
          marginTop: 4,
          letterSpacing: 1.5,
          textTransform: 'uppercase',
          color: isActive ? color : `${color}88`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 5,
        }}>
          {isActive && (
            <span style={{
              display: 'inline-block',
              width: 5,
              height: 5,
              borderRadius: '50%',
              background: color,
              boxShadow: `0 0 6px ${color}`,
              animation: 'node-pulse 1.8s ease-in-out infinite',
            }} />
          )}
          {status}
        </div>
      )}

      {badgeCount > 0 && (
        <div style={{
          position: 'absolute',
          top: -9, right: -9,
          background: alertColor === '#ef4444' ? '#ef4444' : '#f97316',
          color: '#fff',
          borderRadius: '50%',
          width: 20, height: 20,
          fontSize: 10,
          fontWeight: 700,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: `0 0 6px ${alertColor || '#f97316'}`,
        }}>
          {badgeCount > 9 ? '9+' : badgeCount}
        </div>
      )}

      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  )
}

// ── Agent node ───────────────────────────────────────────────────────
function AgentNode({ data }) {
  const { title, committee, status, classification, toolHistory, onChat, onFinding } = data
  const color      = COMMITTEE_COLORS[committee] || '#94a3b8'
  const alertColor = classificationColor(classification)
  const isActive   = status === 'active'
  const hasAlert   = !!alertColor

  const recentTools = (toolHistory || []).slice(-3).reverse()

  return (
    <div style={{
      background: '#080e1a',
      border: `1px solid ${alertColor ? alertColor + '88' : color + '55'}`,
      borderRadius: 6,
      padding: '8px 12px 8px 12px',
      color: `${color}cc`,
      fontSize: 11,
      minWidth: 150,
      position: 'relative',
      boxShadow: isActive ? `0 0 10px 2px ${color}33` : 'none',
      transition: 'box-shadow 0.4s, border-color 0.3s',
      userSelect: 'none',
    }}>
      <Handle type="target" position={Position.Top}    style={{ visibility: 'hidden' }} />

      {/* (!) badge — top-left, appears on warn/critical */}
      {hasAlert && (
        <div
          title="View finding"
          onClick={(e) => { e.stopPropagation(); onFinding() }}
          style={{
            position: 'absolute',
            top: -8, left: -8,
            width: 17, height: 17,
            borderRadius: '50%',
            background: alertColor,
            color: '#fff',
            fontSize: 10,
            fontWeight: 900,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            boxShadow: `0 0 6px ${alertColor}`,
            zIndex: 10,
            lineHeight: 1,
          }}
        >
          !
        </div>
      )}

      {/* (?) badge — top-right, available when agent is active */}
      {isActive && (
        <div
          title="Chat with agent"
          onClick={(e) => { e.stopPropagation(); onChat() }}
          style={{
            position: 'absolute',
            top: -8, right: -8,
            width: 17, height: 17,
            borderRadius: '50%',
            background: '#0f172a',
            border: `1px solid ${color}88`,
            color,
            fontSize: 10,
            fontWeight: 700,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            zIndex: 10,
            lineHeight: 1,
            transition: 'background 0.15s',
          }}
        >
          ?
        </div>
      )}

      {/* Title */}
      <div style={{ fontWeight: 700, fontSize: 11, marginBottom: recentTools.length ? 5 : 0 }}>
        {title}
      </div>

      {/* Tool micro-feed — last 3, newest on top */}
      {recentTools.map((t, i) => (
        <div key={i} style={{
          fontSize: 9,
          color: i === 0 ? `${color}99` : `${color}44`,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          maxWidth: 160,
          lineHeight: 1.5,
        }}>
          › {t.tool}
        </div>
      ))}

      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  )
}

const nodeTypes = { committee: CommitteeNode, agent: AgentNode }

// Wider spread so committees don't crowd each other
const TOP_LEVEL_POSITIONS = {
  orchestrator: { x: 400, y: 0 },
  recon:        { x: 0,   y: 210 },
  planning:     { x: 270, y: 210 },
  retrieval:    { x: 540, y: 210 },
  reporting:    { x: 810, y: 210 },
}

const AGENT_COLUMN_OFFSET_Y = 130
const AGENT_ROW_GAP = 85

const COMMITTEE_LABELS = {
  orchestrator: 'Orchestrator',
  recon:        'Recon',
  planning:     'Planning',
  retrieval:    'Retrieval',
  reporting:    'Reporting',
}

export function CommitteeGraph({ state, dispatch }) {
  const { committees, agents, engagement } = state

  const committeeNodes = useMemo(() =>
    Object.entries(TOP_LEVEL_POSITIONS).map(([key, pos]) => {
      const data = committees[key] || {}
      return {
        id: `committee-${key}`,
        type: 'committee',
        position: pos,
        data: {
          label: COMMITTEE_LABELS[key],
          committee: key,
          status: key === 'orchestrator'
            ? (engagement.status === 'running' ? 'active' : engagement.status === 'completed' ? 'completed' : 'inactive')
            : (data.status || 'inactive'),
          classification: data.classification || null,
          badgeCount: data.badgeCount || 0,
          onClick: () => data.badgeCount > 0 && dispatch({ type: 'DISMISS_BADGE', payload: { committee: key } }),
        },
      }
    }),
    [committees, engagement.status, dispatch]
  )

  const agentNodes = useMemo(() => {
    const byCommittee = {}
    Object.values(agents).forEach(a => {
      if (!byCommittee[a.committee]) byCommittee[a.committee] = []
      byCommittee[a.committee].push(a)
    })

    const nodes = []
    Object.entries(byCommittee).forEach(([committee, list]) => {
      const parentPos = TOP_LEVEL_POSITIONS[committee] || { x: 400, y: 210 }
      list.forEach((agent, i) => {
        nodes.push({
          id: `agent-${agent.id}`,
          type: 'agent',
          position: {
            x: parentPos.x + 8,
            y: parentPos.y + AGENT_COLUMN_OFFSET_Y + i * AGENT_ROW_GAP,
          },
          data: {
            title: agent.title || agent.id.split('.').pop(),
            committee,
            status: agent.status,
            classification: agent.classification || null,
            toolHistory: agent.toolHistory || [],
            onChat: () => dispatch({
              type: 'OPEN_CHAT',
              payload: { agentId: agent.id, agentTitle: agent.title || agent.id, findings: agent.findings || [] },
            }),
            onFinding: () => dispatch({
              type: 'OPEN_CHAT',
              payload: { agentId: agent.id, agentTitle: agent.title || agent.id, findings: agent.findings || [], focusFindings: true },
            }),
          },
        })
      })
    })
    return nodes
  }, [agents, dispatch])

  const edges = useMemo(() => {
    const base = [
      { id: 'e-orch-recon',     source: 'committee-orchestrator', target: 'committee-recon',     type: 'smoothstep', animated: committees.recon?.status     === 'active', style: { stroke: committees.recon?.status     === 'active' ? '#f9731655' : '#1e293b' } },
      { id: 'e-orch-planning',  source: 'committee-orchestrator', target: 'committee-planning',  type: 'smoothstep', animated: committees.planning?.status  === 'active', style: { stroke: committees.planning?.status  === 'active' ? '#22c55e55' : '#1e293b' } },
      { id: 'e-orch-retrieval', source: 'committee-orchestrator', target: 'committee-retrieval', type: 'smoothstep', animated: committees.retrieval?.status === 'active', style: { stroke: committees.retrieval?.status === 'active' ? '#ef444455' : '#1e293b' } },
      { id: 'e-orch-reporting', source: 'committee-orchestrator', target: 'committee-reporting', type: 'smoothstep', animated: committees.reporting?.status === 'active', style: { stroke: committees.reporting?.status === 'active' ? '#eab30855' : '#1e293b' } },
    ]
    Object.values(agents).forEach(agent => {
      const color = COMMITTEE_COLORS[agent.committee] || '#94a3b8'
      base.push({
        id: `e-${agent.committee}-${agent.id}`,
        source: `committee-${agent.committee}`,
        target: `agent-${agent.id}`,
        type: 'smoothstep',
        animated: agent.status === 'active',
        style: { stroke: agent.status === 'active' ? `${color}66` : `${color}22` },
      })
    })
    return base
  }, [agents, committees])

  const allNodes = useMemo(() => [...committeeNodes, ...agentNodes], [committeeNodes, agentNodes])

  return (
    <div style={{ width: '100%', height: '100%' }}>
      <style>{`
        @keyframes node-pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.3; }
        }
      `}</style>
      <ReactFlow
        nodes={allNodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={true}
        zoomOnScroll={true}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#0f172a" gap={28} />
      </ReactFlow>
    </div>
  )
}
