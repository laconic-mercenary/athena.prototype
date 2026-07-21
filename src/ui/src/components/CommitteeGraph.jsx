import { useCallback, useMemo } from 'react'
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

// Only critical and warn trigger the (!) badge — info findings are recorded but
// don't warrant interrupting the operator.
const FINDING_BORDER = {
  signal_critical: '#ef4444',
  signal_warn:     '#f97316',
}

const FINDING_LABEL = {
  signal_critical: 'CRIT',
  signal_warn:     'WARN',
  signal_info:     'INFO',
}

// ── Finding node (grey artifact) ────────────────────────────────────
function FindingNode({ data }) {
  const { finding, onOpenChat } = data
  const color  = FINDING_BORDER[finding.classification] || '#475569'
  const label  = FINDING_LABEL[finding.classification]
  const isCrit = finding.classification === 'signal_critical'
  const isWarn = finding.classification === 'signal_warn'

  return (
    <div
      // Clicks are handled by ReactFlow's onNodeClick (below) rather than an inner
      // onClick — React Flow drives panning off native pointer events, so an inner
      // handler gets swallowed by the pan. nopan keeps a click from starting a pan.
      className="nodrag nopan"
      title={onOpenChat ? 'Discuss this finding with the committee lead' : undefined}
      style={{
      background: '#07101f',
      border: `1px solid ${color}44`,
      borderLeft: `3px solid ${color}`,
      borderRadius: 4,
      padding: '7px 11px',
      width: 220,
      boxShadow: (isCrit || isWarn) ? `0 0 16px ${color}2a` : 'none',
      animation: isCrit ? 'node-pulse 2s ease-in-out infinite' : 'none',
      userSelect: 'none',
      cursor: onOpenChat ? 'pointer' : 'default',
    }}>
      <Handle type="target" position={Position.Left}  style={{ visibility: 'hidden' }} />
      {label && (
        <div style={{
          fontSize: 8,
          fontWeight: 800,
          letterSpacing: 2,
          color,
          textTransform: 'uppercase',
          marginBottom: 4,
        }}>
          {label}
        </div>
      )}
      <div style={{
        fontSize: 10,
        color: '#64748b',
        lineHeight: 1.5,
        display: '-webkit-box',
        WebkitLineClamp: 2,
        WebkitBoxOrient: 'vertical',
        overflow: 'hidden',
      }}>
        {finding.summary}
      </div>
      <Handle type="source" position={Position.Right} style={{ visibility: 'hidden' }} />
    </div>
  )
}

// ── Committee node ───────────────────────────────────────────────────
function CommitteeNode({ data }) {
  const { label, committee, status, classification, badgeCount, onClick } = data
  const color      = COMMITTEE_COLORS[committee] || '#94a3b8'
  const alertColor = FINDING_BORDER[classification]
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
        boxShadow: isActive ? `0 0 18px 4px ${color}44` : 'none',
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
          color: isActive ? color : `${color}66`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 5,
        }}>
          {isActive && (
            <span style={{
              display: 'inline-block',
              width: 5, height: 5,
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
          background: alertColor || '#f97316',
          color: '#fff',
          borderRadius: '50%',
          width: 20, height: 20,
          fontSize: 10, fontWeight: 700,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
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
  const { title, committee, status, classification, toolHistory, isLeader, onChat, onFinding } = data
  const color      = COMMITTEE_COLORS[committee] || '#94a3b8'
  const alertColor = FINDING_BORDER[classification]
  const isActive   = status === 'active'
  const hasAlert   = !!alertColor

  const recentTools = (toolHistory || []).slice(-3).reverse()

  return (
    <div style={{
      background: '#080e1a',
      border: `1px solid ${alertColor ? alertColor + '88' : color + '44'}`,
      borderRadius: 6,
      padding: '8px 12px',
      minWidth: 155,
      position: 'relative',
      boxShadow: isActive ? `0 0 10px 2px ${color}2a` : 'none',
      transition: 'box-shadow 0.4s',
      userSelect: 'none',
    }}>
      <Handle type="target" position={Position.Top}    style={{ visibility: 'hidden' }} />

      {/* (!) badge — finding alert; routes to committee lead (has the operator queue) */}
      {hasAlert && (
        <div
          className="nopan nodrag"
          title="View findings"
          onPointerDown={e => e.stopPropagation()}
          onClick={e => { e.stopPropagation(); onFinding() }}
          style={{
            position: 'absolute', top: -8, left: -8,
            width: 17, height: 17, borderRadius: '50%',
            background: alertColor, color: '#fff',
            fontSize: 10, fontWeight: 900,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: 'pointer',
            boxShadow: `0 0 6px ${alertColor}`,
            zIndex: 10, lineHeight: 1,
          }}
        >
          !
        </div>
      )}

      {/* (?) badge — only leaders have an operator queue */}
      {isActive && isLeader && (
        <div
          className="nopan nodrag"
          title="Chat with lead"
          onPointerDown={e => e.stopPropagation()}
          onClick={e => { e.stopPropagation(); onChat() }}
          style={{
            position: 'absolute', top: -8, right: -8,
            width: 17, height: 17, borderRadius: '50%',
            background: '#0f172a',
            border: `1px solid ${color}88`,
            color, fontSize: 10, fontWeight: 700,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: 'pointer', zIndex: 10, lineHeight: 1,
          }}
        >
          ?
        </div>
      )}

      <div style={{ fontWeight: 700, fontSize: 11, color: `${color}cc`, marginBottom: recentTools.length ? 5 : 0 }}>
        {title}
      </div>

      {recentTools.map((t, i) => (
        <div key={i} style={{
          fontSize: 9,
          color: i === 0 ? `${color}88` : `${color}33`,
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          maxWidth: 160, lineHeight: 1.5,
        }}>
          › {t.tool}
        </div>
      ))}

      {/* Processing bar — 2px strip at bottom, slides while active */}
      {isActive && (
        <div style={{
          position: 'absolute', bottom: 0, left: 0, right: 0,
          height: 2, borderRadius: '0 0 6px 6px', overflow: 'hidden',
          background: `${color}18`,
        }}>
          <div style={{
            width: '38%', height: '100%',
            background: `linear-gradient(90deg, transparent, ${color}, transparent)`,
            animation: 'slide-bar 1.4s linear infinite',
          }} />
        </div>
      )}

      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  )
}

const nodeTypes = { committee: CommitteeNode, agent: AgentNode, finding: FindingNode }

const TOP_LEVEL_POSITIONS = {
  orchestrator: { x: 400, y: 0 },
  recon:        { x: 0,   y: 210 },
  planning:     { x: 270, y: 210 },
  retrieval:    { x: 540, y: 210 },
  reporting:    { x: 810, y: 210 },
}

const AGENT_COLUMN_OFFSET_Y = 130
const AGENT_ROW_GAP         = 85
const FINDING_X             = 1280
const FINDING_START_Y       = 50
const FINDING_GAP           = 88

const COMMITTEE_LABELS = {
  orchestrator: 'Orchestrator',
  recon:        'Recon',
  planning:     'Planning',
  retrieval:    'Retrieval',
  reporting:    'Reporting',
}

export function CommitteeGraph({ state, dispatch }) {
  const { committees, agents, engagement } = state

  // ── Committee nodes ───────────────────────────────────────────────
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

  // ── Agent nodes ───────────────────────────────────────────────────
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
          position: { x: parentPos.x + 8, y: parentPos.y + AGENT_COLUMN_OFFSET_Y + i * AGENT_ROW_GAP },
          data: {
            title: agent.title || agent.id.split('.').pop(),
            committee,
            status: agent.status,
            classification: agent.classification || null,
            toolHistory: agent.toolHistory || [],
            isLeader: agent.id.endsWith('.leader'),
            onChat: () => dispatch({
              type: 'OPEN_CHAT',
              payload: { agentId: agent.id, agentTitle: agent.title || agent.id, findings: agent.findings || [] },
            }),
            // (!) always targets the committee leader (has the operator queue).
            // For specialist agents we route to their lead and show the specialist's own findings.
            onFinding: () => {
              const leaderId    = agent.id.endsWith('.leader') ? agent.id : `athena.${committee}.leader`
              const leaderTitle = agents[leaderId]?.title || `${committee} lead`
              dispatch({
                type: 'OPEN_CHAT',
                payload: { agentId: leaderId, agentTitle: leaderTitle, findings: agent.findings || [], focusFindings: true },
              })
            },
          },
        })
      })
    })
    return nodes
  }, [agents, dispatch])

  // ── Hierarchy edges (committee ↔ committee, committee ↔ agent) ────
  const hierarchyEdges = useMemo(() => {
    const base = [
      { id: 'e-orch-recon',     source: 'committee-orchestrator', target: 'committee-recon',     type: 'smoothstep', animated: committees.recon?.status     === 'active', style: { stroke: committees.recon?.status     === 'active' ? '#f9731644' : '#1a2540' } },
      { id: 'e-orch-planning',  source: 'committee-orchestrator', target: 'committee-planning',  type: 'smoothstep', animated: committees.planning?.status  === 'active', style: { stroke: committees.planning?.status  === 'active' ? '#22c55e44' : '#1a2540' } },
      { id: 'e-orch-retrieval', source: 'committee-orchestrator', target: 'committee-retrieval', type: 'smoothstep', animated: committees.retrieval?.status === 'active', style: { stroke: committees.retrieval?.status === 'active' ? '#ef444444' : '#1a2540' } },
      { id: 'e-orch-reporting', source: 'committee-orchestrator', target: 'committee-reporting', type: 'smoothstep', animated: committees.reporting?.status === 'active', style: { stroke: committees.reporting?.status === 'active' ? '#eab30844' : '#1a2540' } },
    ]
    Object.values(agents).forEach(agent => {
      const color = COMMITTEE_COLORS[agent.committee] || '#94a3b8'
      const active = agent.status === 'active'
      base.push({
        id: `e-comm-${agent.id}`,
        source: `committee-${agent.committee}`,
        target: `agent-${agent.id}`,
        type: 'smoothstep',
        animated: active,
        style: { stroke: active ? `${color}55` : `${color}1a` },
      })
    })
    return base
  }, [agents, committees])

  // ── Finding nodes + discovery edges + swarm edges ─────────────────
  const { findingNodes, findingEdges } = useMemo(() => {
    const nodes = []
    const edges = []

    // Collect displayable findings across all agents, sorted by discovery time
    const allFindings = []
    Object.values(agents).forEach(agent => {
      ;(agent.findings || []).forEach((finding, idx) => {
        if (finding.classification === 'noise' || finding.classification === 'unknown') return
        allFindings.push({
          finding,
          agentId: agent.id,
          committee: agent.committee,
          agentStatus: agent.status,
          nodeId: `finding-${agent.id}-${idx}`,
        })
      })
    })
    allFindings.sort((a, b) => a.finding.ts - b.finding.ts)

    // Create finding nodes
    allFindings.forEach((f, i) => {
      // Chat targets the committee lead: it is a valid operator-queue target and
      // is where recon findings are attributed. Pass the lead's full finding set
      // so the chat's Findings tab shows every critical/warn, not just this one.
      const leaderId = `athena.${f.committee}.leader`
      nodes.push({
        id: f.nodeId,
        type: 'finding',
        position: { x: FINDING_X, y: FINDING_START_Y + i * FINDING_GAP },
        data: {
          finding: f.finding,
          agentId: f.agentId,
          committee: f.committee,
          onOpenChat: () => dispatch({
            type: 'OPEN_CHAT',
            payload: {
              agentId: leaderId,
              agentTitle: agents[leaderId]?.title || `${f.committee} lead`,
              findings: agents[leaderId]?.findings || [f.finding],
              focusFindings: true,
            },
          }),
        },
      })

      // Discovery edge: discovering agent → finding
      const color = COMMITTEE_COLORS[f.committee] || '#94a3b8'
      edges.push({
        id: `e-disc-${f.nodeId}`,
        source: `agent-${f.agentId}`,
        target: f.nodeId,
        type: 'smoothstep',
        animated: f.agentStatus === 'active',
        style: {
          stroke: `${color}55`,
          strokeDasharray: '5 4',
          strokeWidth: 1,
        },
      })
    })

    // Swarm edges: retrieval agents → all alert-level findings
    const alertFindings = allFindings.filter(
      f => f.finding.classification === 'signal_critical' || f.finding.classification === 'signal_warn'
    )

    if (alertFindings.length > 0) {
      Object.values(agents)
        .filter(a => a.committee === 'retrieval')
        .forEach(agent => {
          alertFindings.forEach(f => {
            const edgeColor = FINDING_BORDER[f.finding.classification] || '#ef4444'
            edges.push({
              id: `e-swarm-${agent.id}-${f.nodeId}`,
              source: `agent-${agent.id}`,
              target: f.nodeId,
              type: 'smoothstep',
              animated: agent.status === 'active',
              style: {
                stroke: `${edgeColor}77`,
                strokeWidth: 1.5,
              },
            })
          })
        })
    }

    return { findingNodes: nodes, findingEdges: edges }
  }, [agents, dispatch])

  const allNodes = useMemo(
    () => [...committeeNodes, ...agentNodes, ...findingNodes],
    [committeeNodes, agentNodes, findingNodes]
  )

  const allEdges = useMemo(
    () => [...hierarchyEdges, ...findingEdges],
    [hierarchyEdges, findingEdges]
  )

  // React Flow's own click detection — fires on a genuine click (not a pan) even
  // with panOnDrag enabled, which an inner node onClick cannot reliably do.
  const onNodeClick = useCallback((_event, node) => {
    if (node.data?.onOpenChat) node.data.onOpenChat()
  }, [])

  return (
    <div style={{ width: '100%', height: '100%' }}>
      <style>{`
        @keyframes node-pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.35; }
        }
        @keyframes slide-bar {
          0%   { transform: translateX(-100%); }
          100% { transform: translateX(360%); }
        }
      `}</style>
      <ReactFlow
        nodes={allNodes}
        edges={allEdges}
        nodeTypes={nodeTypes}
        onNodeClick={onNodeClick}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={true}
        zoomOnScroll={true}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#0a1628" gap={30} />
      </ReactFlow>
    </div>
  )
}
