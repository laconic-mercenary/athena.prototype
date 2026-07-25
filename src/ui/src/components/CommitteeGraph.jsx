import { useCallback, useMemo } from 'react'
import {
  ReactFlow,
  Background,
  Handle,
  Position,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

// Palette assigned by committee index for dynamic ensembles.
const COMMITTEE_PALETTE = ['#f97316', '#22c55e', '#ef4444', '#eab308', '#3b82f6', '#a855f7', '#06b6d4']

function committeeColor(name, index) {
  const fixed = { orchestrator: '#e2e8f0' }
  return fixed[name] || COMMITTEE_PALETTE[index % COMMITTEE_PALETTE.length]
}

const FINDING_BORDER = { signal_critical: '#ef4444', signal_warn: '#f97316' }
const FINDING_LABEL  = { signal_critical: 'CRIT', signal_warn: 'WARN', signal_info: 'INFO' }
const GATE_COLORS    = { advance: '#22c55e', retry: '#ef4444', iterate: '#f97316' }

// ── Step rail ────────────────────────────────────────────────────────────────
function StepRail({ steps, color }) {
  if (!steps || steps.length === 0) return null
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 4,
      marginTop: 8,
      paddingTop: 8,
      borderTop: `1px solid ${color}1a`,
      flexWrap: 'wrap',
    }}>
      {steps.map((step, i) => {
        const isDone   = step.status === 'done'
        const isActive = step.status === 'active'
        return (
          <div
            key={step.id}
            title={step.description}
            style={{
              width: 7, height: 7,
              borderRadius: '50%',
              background: isDone
                ? `${color}88`
                : isActive
                ? color
                : `${color}22`,
              boxShadow: isActive ? `0 0 5px ${color}` : 'none',
              animation: isActive ? 'node-pulse 1.8s ease-in-out infinite' : 'none',
              flexShrink: 0,
              cursor: 'default',
            }}
          />
        )
      })}
      {steps.length > 0 && (
        <span style={{ fontSize: 8, color: `${color}55`, marginLeft: 2 }}>
          {steps.filter(s => s.status === 'done').length}/{steps.length}
        </span>
      )}
    </div>
  )
}

// ── Finding node ─────────────────────────────────────────────────────────────
function FindingNode({ data }) {
  const { finding, onOpenChat } = data
  const color  = FINDING_BORDER[finding.classification] || '#475569'
  const label  = FINDING_LABEL[finding.classification]
  const isCrit = finding.classification === 'signal_critical'

  return (
    <div
      className="nodrag nopan"
      title={onOpenChat ? 'Discuss this finding with the committee lead' : undefined}
      style={{
        background: '#07101f',
        border: `1px solid ${color}44`,
        borderLeft: `3px solid ${color}`,
        borderRadius: 4,
        padding: '7px 11px',
        width: 220,
        boxShadow: isCrit ? `0 0 16px ${color}2a` : 'none',
        animation: isCrit ? 'node-pulse 2s ease-in-out infinite' : 'none',
        userSelect: 'none',
        cursor: onOpenChat ? 'pointer' : 'default',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ visibility: 'hidden' }} />
      {label && (
        <div style={{ fontSize: 8, fontWeight: 800, letterSpacing: 2, color, textTransform: 'uppercase', marginBottom: 4 }}>
          {label}
        </div>
      )}
      <div style={{
        fontSize: 10, color: '#64748b', lineHeight: 1.5,
        display: '-webkit-box', WebkitLineClamp: 2,
        WebkitBoxOrient: 'vertical', overflow: 'hidden',
      }}>
        {finding.summary}
      </div>
      <Handle type="source" position={Position.Right} style={{ visibility: 'hidden' }} />
    </div>
  )
}

// ── Committee node ────────────────────────────────────────────────────────────
function CommitteeNode({ data }) {
  const { label, color, status, classification, badgeCount, steps, onClick } = data
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
        opacity: isDone ? 0.75 : 1,
        transition: 'box-shadow 0.4s, border-color 0.3s',
        position: 'relative',
        userSelect: 'none',
      }}
    >
      <Handle type="target" position={Position.Top}    style={{ visibility: 'hidden' }} />

      <div style={{ letterSpacing: 1 }}>{label}</div>

      {status !== 'inactive' && (
        <div style={{
          fontSize: 9, marginTop: 4, letterSpacing: 1.5,
          textTransform: 'uppercase',
          color: isActive ? color : `${color}66`,
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5,
        }}>
          {isActive && (
            <span style={{
              display: 'inline-block', width: 5, height: 5, borderRadius: '50%',
              background: color, boxShadow: `0 0 6px ${color}`,
              animation: 'node-pulse 1.8s ease-in-out infinite',
            }} />
          )}
          {status}
        </div>
      )}

      <StepRail steps={steps} color={color} />

      {badgeCount > 0 && (
        <div style={{
          position: 'absolute', top: -9, right: -9,
          background: alertColor || '#f97316', color: '#fff',
          borderRadius: '50%', width: 20, height: 20,
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

// ── Agent node ────────────────────────────────────────────────────────────────
function AgentNode({ data }) {
  const { title, color, status, classification, toolHistory, isLeader, onChat, onFinding } = data
  const alertColor = FINDING_BORDER[classification]
  const isActive   = status === 'active'
  const hasAlert   = !!alertColor

  const recentTools = (toolHistory || []).slice(-3).reverse()

  return (
    <div style={{
      background: '#080e1a',
      border: `1px solid ${alertColor ? alertColor + '88' : color + '44'}`,
      borderRadius: 6, padding: '8px 12px', minWidth: 155,
      position: 'relative',
      boxShadow: isActive ? `0 0 10px 2px ${color}2a` : 'none',
      transition: 'box-shadow 0.4s', userSelect: 'none',
    }}>
      <Handle type="target" position={Position.Top}    style={{ visibility: 'hidden' }} />

      {hasAlert && (
        <div className="nopan nodrag" title="View findings" onPointerDown={e => e.stopPropagation()}
          onClick={e => { e.stopPropagation(); onFinding() }}
          style={{
            position: 'absolute', top: -8, left: -8,
            width: 17, height: 17, borderRadius: '50%',
            background: alertColor, color: '#fff',
            fontSize: 10, fontWeight: 900,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: 'pointer', boxShadow: `0 0 6px ${alertColor}`, zIndex: 10, lineHeight: 1,
          }}
        >!</div>
      )}

      {isActive && isLeader && (
        <div className="nopan nodrag" title="Chat with lead" onPointerDown={e => e.stopPropagation()}
          onClick={e => { e.stopPropagation(); onChat() }}
          style={{
            position: 'absolute', top: -8, right: -8,
            width: 17, height: 17, borderRadius: '50%',
            background: '#0f172a', border: `1px solid ${color}88`,
            color, fontSize: 10, fontWeight: 700,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: 'pointer', zIndex: 10, lineHeight: 1,
          }}
        >?</div>
      )}

      <div style={{ fontWeight: 700, fontSize: 11, color: `${color}cc`, marginBottom: recentTools.length ? 5 : 0 }}>
        {title}
      </div>

      {recentTools.map((t, i) => (
        <div key={i} style={{
          fontSize: 9, color: i === 0 ? `${color}88` : `${color}33`,
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          maxWidth: 160, lineHeight: 1.5,
        }}>
          › {t.tool}
        </div>
      ))}

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

const ORCH_POS  = { x: 0, y: 0 }
const COMM_Y    = 210
const COMM_GAP  = 230
const AGENT_OFFSET_Y = 130
const AGENT_ROW_GAP  = 85
const FINDING_GAP    = 88
const FINDING_INIT_Y = 0

function computeCommitteePositions(committeeNames) {
  const n = committeeNames.length
  const totalWidth = (n - 1) * COMM_GAP
  const orchX = totalWidth / 2
  const positions = { orchestrator: { x: orchX, y: ORCH_POS.y } }
  committeeNames.forEach((name, i) => {
    positions[name] = { x: i * COMM_GAP, y: COMM_Y }
  })
  return positions
}

export function CommitteeGraph({ state, dispatch }) {
  const { committees, agents, steps, engagement, gateDecisions, plan } = state

  const committeeNames = useMemo(() => Object.keys(committees), [committees])
  const positions      = useMemo(() => computeCommitteePositions(committeeNames), [committeeNames])

  const findingX = useMemo(() => {
    if (committeeNames.length === 0) return 600
    return Math.max(...committeeNames.map((_, i) => i * COMM_GAP)) + 280
  }, [committeeNames])

  // ── Orchestrator node ─────────────────────────────────────────────────────
  const orchestratorNode = useMemo(() => {
    const pos   = positions.orchestrator || { x: 0, y: 0 }
    const color = committeeColor('orchestrator', -1)
    return {
      id: 'committee-orchestrator',
      type: 'committee',
      position: pos,
      data: {
        label: 'Orchestrator',
        color,
        status: engagement.status === 'running'
          ? 'active'
          : engagement.status === 'completed' ? 'completed' : 'inactive',
        classification: null,
        badgeCount: 0,
        steps: [],
        onClick: () => {},
      },
    }
  }, [positions, engagement.status])

  // ── Committee nodes ───────────────────────────────────────────────────────
  const committeeNodes = useMemo(() =>
    committeeNames.map((name, i) => {
      const pos   = positions[name] || { x: i * COMM_GAP, y: COMM_Y }
      const data  = committees[name] || {}
      const color = committeeColor(name, i)
      return {
        id: `committee-${name}`,
        type: 'committee',
        position: pos,
        data: {
          label: name,
          color,
          status: data.status || 'inactive',
          classification: data.classification || null,
          badgeCount: data.badgeCount || 0,
          steps: steps[name] || [],
          onClick: () => data.badgeCount > 0 && dispatch({ type: 'DISMISS_BADGE', payload: { committee: name } }),
        },
      }
    }),
    [committeeNames, committees, positions, steps, dispatch]
  )

  // ── Agent nodes ───────────────────────────────────────────────────────────
  const agentNodes = useMemo(() => {
    const byCommittee = {}
    Object.values(agents).forEach(a => {
      if (!byCommittee[a.committee]) byCommittee[a.committee] = []
      byCommittee[a.committee].push(a)
    })
    const nodes = []
    Object.entries(byCommittee).forEach(([committee, list]) => {
      const committeeIndex = committeeNames.indexOf(committee)
      const parentPos = positions[committee] || { x: committeeIndex * COMM_GAP, y: COMM_Y }
      const color = committeeColor(committee, committeeIndex)
      list.forEach((agent, i) => {
        nodes.push({
          id: `agent-${agent.id}`,
          type: 'agent',
          position: { x: parentPos.x + 8, y: parentPos.y + AGENT_OFFSET_Y + i * AGENT_ROW_GAP },
          data: {
            title: agent.title || agent.id.split('.').pop(),
            color,
            status: agent.status,
            classification: agent.classification || null,
            toolHistory: agent.toolHistory || [],
            isLeader: agent.id.endsWith('.leader'),
            onChat: () => dispatch({
              type: 'OPEN_CHAT',
              payload: {
                agentId: agent.id,
                committeeId: agent.committee,
                agentTitle: agent.title || agent.id,
                findings: agent.findings || [],
              },
            }),
            onFinding: () => {
              const leaderId = Object.keys(agents).find(
                id => agents[id].committee === committee && id.endsWith('.leader')
              ) || agent.id
              dispatch({
                type: 'OPEN_CHAT',
                payload: {
                  agentId: leaderId,
                  committeeId: committee,
                  agentTitle: agents[leaderId]?.title || `${committee} lead`,
                  findings: agent.findings || [],
                  focusFindings: true,
                },
              })
            },
          },
        })
      })
    })
    return nodes
  }, [agents, committeeNames, positions, dispatch])

  // ── Edges ─────────────────────────────────────────────────────────────────
  const edges = useMemo(() => {
    const result = []

    // Orchestrator → each committee
    committeeNames.forEach((name, i) => {
      const color = committeeColor(name, i)
      const active = committees[name]?.status === 'active'
      result.push({
        id: `e-orch-${name}`,
        source: 'committee-orchestrator',
        target: `committee-${name}`,
        type: 'smoothstep',
        animated: active,
        style: { stroke: active ? `${color}66` : '#1a2540' },
      })
    })

    // Forward committee → committee (in plan order)
    committeeNames.forEach((name, i) => {
      if (i < committeeNames.length - 1) {
        const nextName = committeeNames[i + 1]
        const color    = committeeColor(nextName, i + 1)
        const advancing = gateDecisions.some(
          g => g.committee === name && g.decision === 'advance' && (!g.to || g.to === nextName)
        )
        result.push({
          id: `e-fwd-${name}-${nextName}`,
          source: `committee-${name}`,
          target: `committee-${nextName}`,
          type: 'smoothstep',
          animated: advancing,
          style: { stroke: advancing ? `${color}88` : '#1a2540' },
        })
      }
    })

    // Back-edges from gate decisions (retry / iterate)
    gateDecisions.forEach((g, idx) => {
      if ((g.decision === 'retry' || g.decision === 'iterate') && g.to) {
        const edgeColor = GATE_COLORS[g.decision]
        result.push({
          id: `e-back-${idx}`,
          source: `committee-${g.committee}`,
          target: `committee-${g.to}`,
          type: 'smoothstep',
          style: {
            stroke: `${edgeColor}88`,
            strokeDasharray: '5 4',
            strokeWidth: 1.5,
          },
          label: g.decision === 'retry' ? '↩ retry' : '↻ iterate',
          labelStyle: { fontSize: 8, fill: edgeColor },
          labelBgStyle: { fill: '#07101f' },
        })
      }
    })

    // Committee → agent edges
    Object.values(agents).forEach(agent => {
      const committeeIndex = committeeNames.indexOf(agent.committee)
      const color = committeeColor(agent.committee, committeeIndex)
      const active = agent.status === 'active'
      result.push({
        id: `e-comm-${agent.id}`,
        source: `committee-${agent.committee}`,
        target: `agent-${agent.id}`,
        type: 'smoothstep',
        animated: active,
        style: { stroke: active ? `${color}55` : `${color}1a` },
      })
    })

    return result
  }, [committeeNames, committees, agents, gateDecisions])

  // ── Finding nodes + edges ─────────────────────────────────────────────────
  const { findingNodes, findingEdges } = useMemo(() => {
    const nodes = []
    const edges = []

    const allFindings = []
    Object.values(agents).forEach(agent => {
      ;(agent.findings || []).forEach((finding, idx) => {
        if (finding.classification === 'noise' || finding.classification === 'unknown') return
        allFindings.push({ finding, agentId: agent.id, committee: agent.committee, agentStatus: agent.status, nodeId: `finding-${agent.id}-${idx}` })
      })
    })
    allFindings.sort((a, b) => a.finding.ts - b.finding.ts)

    allFindings.forEach((f, i) => {
      const committeeIndex = committeeNames.indexOf(f.committee)
      const color = committeeColor(f.committee, committeeIndex)
      const leaderId = Object.keys(agents).find(id => agents[id].committee === f.committee && id.endsWith('.leader'))
      nodes.push({
        id: f.nodeId,
        type: 'finding',
        position: { x: findingX, y: FINDING_INIT_Y + i * FINDING_GAP },
        data: {
          finding: f.finding,
          onOpenChat: () => dispatch({
            type: 'OPEN_CHAT',
            payload: {
              agentId: leaderId || f.agentId,
              committeeId: f.committee,
              agentTitle: (leaderId && agents[leaderId]?.title) || `${f.committee} lead`,
              findings: (leaderId && agents[leaderId]?.findings) || [f.finding],
              focusFindings: true,
            },
          }),
        },
      })
      edges.push({
        id: `e-disc-${f.nodeId}`,
        source: `agent-${f.agentId}`,
        target: f.nodeId,
        type: 'smoothstep',
        animated: f.agentStatus === 'active',
        style: { stroke: `${color}55`, strokeDasharray: '5 4', strokeWidth: 1 },
      })
    })

    return { findingNodes: nodes, findingEdges: edges }
  }, [agents, committeeNames, findingX, dispatch])

  const allNodes = useMemo(
    () => [orchestratorNode, ...committeeNodes, ...agentNodes, ...findingNodes],
    [orchestratorNode, committeeNodes, agentNodes, findingNodes]
  )

  const allEdges = useMemo(
    () => [...edges, ...findingEdges],
    [edges, findingEdges]
  )

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
        fitViewOptions={{ padding: 0.25 }}
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
