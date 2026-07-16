import { useMemo } from 'react'
import {
  ReactFlow,
  Background,
  Handle,
  Position,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

const COMMITTEE_COLORS = {
  recon:     '#f97316',
  planning:  '#22c55e',
  retrieval: '#ef4444',
  reporting: '#eab308',
}

const FINDING_BORDER = {
  signal_critical: '#ef4444',
  signal_warn:     '#f97316',
  signal_info:     '#3b82f6',
}

const FINDING_LABEL = {
  signal_critical: 'CRIT',
  signal_warn:     'WARN',
  signal_info:     'INFO',
}

// Which system does each agent target?
function agentSystem(agent) {
  const id = agent.id.toLowerCase()
  const title = (agent.title || '').toLowerCase()
  if (id.includes('db') || title.includes('db') || title.includes('database')) return 'pgdatabase'
  if (agent.committee === 'recon' || agent.committee === 'retrieval') return 'target'
  return null
}

// ── System node (container / host) ──────────────────────────────────
function SystemNode({ data }) {
  const { label, services, activeAgentCount, hasCritical } = data
  return (
    <div style={{
      background: '#0a121e',
      border: `2px solid ${hasCritical ? '#ef444488' : '#2d4060'}`,
      borderRadius: 10,
      padding: '14px 22px',
      minWidth: 220,
      boxShadow: hasCritical ? '0 0 20px #ef44442a' : 'none',
      transition: 'box-shadow 0.4s',
      userSelect: 'none',
      textAlign: 'center',
    }}>
      <Handle type="target" position={Position.Top}    style={{ visibility: 'hidden' }} />

      <div style={{
        fontSize: 9,
        letterSpacing: 2,
        textTransform: 'uppercase',
        color: '#3b5270',
        marginBottom: 6,
      }}>
        container
      </div>

      <div style={{
        fontSize: 14,
        fontWeight: 700,
        color: hasCritical ? '#ef4444' : '#94a3b8',
        letterSpacing: 1,
        marginBottom: 10,
      }}>
        {label}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {services.map(svc => (
          <div key={svc} style={{
            fontSize: 10,
            color: '#3b5270',
            background: '#0d1a2a',
            border: '1px solid #1e3050',
            borderRadius: 3,
            padding: '2px 8px',
          }}>
            {svc}
          </div>
        ))}
      </div>

      {activeAgentCount > 0 && (
        <div style={{
          marginTop: 10,
          fontSize: 9,
          color: '#22c55e',
          letterSpacing: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 5,
        }}>
          <span style={{
            display: 'inline-block',
            width: 5, height: 5,
            borderRadius: '50%',
            background: '#22c55e',
            boxShadow: '0 0 5px #22c55e',
            animation: 'node-pulse 1.8s ease-in-out infinite',
          }} />
          {activeAgentCount} agent{activeAgentCount !== 1 ? 's' : ''} active
        </div>
      )}

      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  )
}

// ── Mini agent node for system view ─────────────────────────────────
function SystemAgentNode({ data }) {
  const { title, committee, status, classification, lastTool, onChat, onFinding } = data
  const color      = COMMITTEE_COLORS[committee] || '#64748b'
  const alertColor = FINDING_BORDER[classification]
  const isActive   = status === 'active'

  return (
    <div style={{
      background: '#080e1a',
      border: `1px solid ${alertColor ? alertColor + '88' : color + '44'}`,
      borderRadius: 6,
      padding: '7px 12px',
      minWidth: 140,
      position: 'relative',
      boxShadow: isActive ? `0 0 10px 2px ${color}22` : 'none',
      transition: 'box-shadow 0.4s',
      userSelect: 'none',
      textAlign: 'center',
    }}>
      <Handle type="target" position={Position.Top}    style={{ visibility: 'hidden' }} />

      {alertColor && (
        <div
          className="nopan nodrag"
          title="View finding"
          onClick={e => { e.stopPropagation(); onFinding() }}
          style={{
            position: 'absolute', top: -7, left: -7,
            width: 15, height: 15, borderRadius: '50%',
            background: alertColor, color: '#fff',
            fontSize: 9, fontWeight: 900,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: 'pointer', boxShadow: `0 0 5px ${alertColor}`,
            zIndex: 10,
          }}
        >!</div>
      )}

      {isActive && (
        <div
          className="nopan nodrag"
          title="Chat with agent"
          onClick={e => { e.stopPropagation(); onChat() }}
          style={{
            position: 'absolute', top: -7, right: -7,
            width: 15, height: 15, borderRadius: '50%',
            background: '#0f172a',
            border: `1px solid ${color}88`,
            color, fontSize: 9, fontWeight: 700,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: 'pointer', zIndex: 10,
          }}
        >?</div>
      )}

      <div style={{ fontWeight: 700, fontSize: 10, color: `${color}cc` }}>{title}</div>
      {lastTool && (
        <div style={{ fontSize: 8, color: `${color}55`, marginTop: 3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 130 }}>
          › {lastTool.tool}
        </div>
      )}

      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  )
}

// ── Finding node ─────────────────────────────────────────────────────
function FindingNode({ data }) {
  const { finding } = data
  const color  = FINDING_BORDER[finding.classification] || '#475569'
  const label  = FINDING_LABEL[finding.classification]
  const isCrit = finding.classification === 'signal_critical'
  const isWarn = finding.classification === 'signal_warn'

  return (
    <div style={{
      background: '#07101f',
      border: `1px solid ${color}44`,
      borderLeft: `3px solid ${color}`,
      borderRadius: 4,
      padding: '7px 11px',
      width: 210,
      boxShadow: (isCrit || isWarn) ? `0 0 14px ${color}2a` : 'none',
      animation: isCrit ? 'node-pulse 2s ease-in-out infinite' : 'none',
      userSelect: 'none',
    }}>
      <Handle type="target" position={Position.Left}  style={{ visibility: 'hidden' }} />
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
    </div>
  )
}

const nodeTypes = { system: SystemNode, systemAgent: SystemAgentNode, finding: FindingNode }

// Known system services — inferred from docker-compose topology
const SYSTEM_SERVICES = {
  target:     ['SSH · 22', 'HTTP · 80'],
  pgdatabase: ['PostgreSQL · 5432'],
}

// Fixed layout anchors for each system
const SYSTEM_POSITIONS = {
  target:     { x: 100,  y: 0 },
  pgdatabase: { x: 600,  y: 0 },
}

const FINDING_X      = 950
const FINDING_GAP    = 88
const FINDING_INIT_Y = 0

export function SystemView({ state, dispatch }) {
  const { agents, engagement } = state
  const primaryTarget = engagement.target || 'target'

  const { systemNodes, agentNodes, findingNodes, allEdges } = useMemo(() => {
    const agentList = Object.values(agents)

    // Map agents to systems
    const agentsBySystem = { target: [], pgdatabase: [] }
    agentList.forEach(a => {
      const sys = agentSystem(a)
      if (sys && agentsBySystem[sys]) agentsBySystem[sys].push(a)
    })

    // Collect displayable findings sorted by time
    const allFindings = []
    agentList.forEach(agent => {
      ;(agent.findings || []).forEach((finding, idx) => {
        if (finding.classification === 'noise' || finding.classification === 'unknown') return
        allFindings.push({ finding, agent, nodeId: `sv-finding-${agent.id}-${idx}` })
      })
    })
    allFindings.sort((a, b) => a.finding.ts - b.finding.ts)

    // ── System nodes ──────────────────────────────────────────────
    const systemIds = Object.keys(SYSTEM_POSITIONS)
    const sNodes = systemIds.map(sysId => {
      const sysAgents = agentsBySystem[sysId] || []
      const activeCount = sysAgents.filter(a => a.status === 'active').length
      const hasCritical = allFindings
        .filter(f => agentSystem(f.agent) === sysId)
        .some(f => f.finding.classification === 'signal_critical')

      return {
        id: `sys-${sysId}`,
        type: 'system',
        position: SYSTEM_POSITIONS[sysId],
        data: {
          label: sysId,
          services: SYSTEM_SERVICES[sysId] || [],
          activeAgentCount: activeCount,
          hasCritical,
        },
      }
    })

    // ── Agent nodes under each system ─────────────────────────────
    const aNodes = []
    const edges  = []

    const AGENT_COLS   = 2
    const AGENT_COL_W  = 170
    const AGENT_ROW_H  = 85
    const AGENT_START_Y = 180

    systemIds.forEach(sysId => {
      const sysPos  = SYSTEM_POSITIONS[sysId]
      const sysAgents = agentsBySystem[sysId] || []

      sysAgents.forEach((agent, i) => {
        const col = i % AGENT_COLS
        const row = Math.floor(i / AGENT_COLS)
        const x   = sysPos.x + col * AGENT_COL_W - (AGENT_COLS - 1) * AGENT_COL_W / 2 + 80
        const y   = AGENT_START_Y + row * AGENT_ROW_H
        const nodeId = `sv-agent-${agent.id}`

        aNodes.push({
          id: nodeId,
          type: 'systemAgent',
          position: { x, y },
          data: {
            title: agent.title || agent.id.split('.').pop(),
            committee: agent.committee,
            status: agent.status,
            classification: agent.classification || null,
            lastTool: agent.lastTool,
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

        // Edge: agent → system (upward)
        const color = COMMITTEE_COLORS[agent.committee] || '#64748b'
        edges.push({
          id: `e-sv-${agent.id}-${sysId}`,
          source: nodeId,
          target: `sys-${sysId}`,
          type: 'smoothstep',
          animated: agent.status === 'active',
          style: { stroke: agent.status === 'active' ? `${color}66` : `${color}22` },
        })
      })
    })

    // ── Finding nodes ─────────────────────────────────────────────
    const fNodes = allFindings.map((f, i) => ({
      id: f.nodeId,
      type: 'finding',
      position: { x: FINDING_X, y: FINDING_INIT_Y + i * FINDING_GAP },
      data: { finding: f.finding },
    }))

    // Discovery edges: agent → finding
    allFindings.forEach(f => {
      const color = COMMITTEE_COLORS[f.agent.committee] || '#94a3b8'
      edges.push({
        id: `e-sv-disc-${f.nodeId}`,
        source: `sv-agent-${f.agent.id}`,
        target: f.nodeId,
        type: 'smoothstep',
        animated: f.agent.status === 'active',
        style: { stroke: `${color}44`, strokeDasharray: '5 4' },
      })
    })

    // System → finding edges for context
    allFindings.forEach(f => {
      const sysId = agentSystem(f.agent) || 'target'
      edges.push({
        id: `e-sv-sys-${f.nodeId}`,
        source: `sys-${sysId}`,
        target: f.nodeId,
        type: 'smoothstep',
        animated: false,
        style: { stroke: '#1e3050', strokeDasharray: '3 5' },
      })
    })

    return { systemNodes: sNodes, agentNodes: aNodes, findingNodes: fNodes, allEdges: edges }
  }, [agents, engagement.target, dispatch])

  const allNodes = useMemo(
    () => [...systemNodes, ...agentNodes, ...findingNodes],
    [systemNodes, agentNodes, findingNodes]
  )

  return (
    <div style={{ width: '100%', height: '100%' }}>
      <style>{`
        @keyframes node-pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.35; }
        }
      `}</style>
      <ReactFlow
        nodes={allNodes}
        edges={allEdges}
        nodeTypes={nodeTypes}
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
