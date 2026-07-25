import { useReducer, useCallback, useEffect } from 'react'
import { useEvents } from './useEvents'
import { EngagementRequest } from './pages/EngagementRequest'
import { OrchestratorDialog } from './pages/OrchestratorDialog'
import { Dashboard } from './pages/Dashboard'
import './index.css'

const INITIAL_COMMITTEE = {
  status: 'inactive',
  badgeCount: 0,
  findings: [],
  classification: null,
  digest: null,
  incomplete: false,
}

function dominantClassification(findings) {
  const ORDER = ['signal_critical', 'signal_warn', 'signal_info', 'noise', 'unknown']
  for (const cls of ORDER) {
    if (findings.some(f => f.classification === cls)) return cls
  }
  return null
}

const initialState = {
  page: 'request',
  engagement: {
    run_id: null,
    status: 'idle',
    awaitingApproval: false,
    awaitingCommittee: null,
  },
  planReady: false,
  plan: null,
  committees: {},
  steps: {},
  gateDecisions: [],
  latestGateDecision: null,
  pendingLeaderQuestions: {},
  agents: {},
  agentReplies: {},
  dialogMessages: [],
  chat: { isOpen: false, agentId: null, committeeId: null, agentTitle: null, findings: [], focusFindings: false },
  latestEvent: null,
  eventLog: [],
}

const GATE_COLORS = { advance: '#22c55e', retry: '#ef4444', iterate: '#f97316' }
const GATE_ICONS  = { advance: '→', retry: '↩', iterate: '↻' }

const EVENT_LOG_MAX = 500
const MESSAGE_LOG_MAX = 200

function appendLog(state, entry) {
  return [...(state.eventLog || []).slice(-(EVENT_LOG_MAX - 1)), entry]
}

// Parse JSON input_summary from backend and format as readable tool call string.
export function formatToolSummary(tool, inputSummary) {
  try {
    const params = JSON.parse(inputSummary)
    const parts = Object.entries(params).map(([k, v]) => {
      if (Array.isArray(v)) return `${v.length} ${k}`
      const s = String(v)
      return s.length > 35 ? `${k}=…${s.slice(-25)}` : `${k}=${s}`
    })
    return parts.length > 0 ? `${tool}(${parts.join(', ')})` : tool
  } catch {
    return tool
  }
}

function reducer(state, action) {
  const { type, payload } = action

  if (type === 'NAVIGATE') return { ...state, page: payload }

  if (type === 'RUN_STARTED') {
    return {
      ...state,
      page: 'dialog',
      engagement: { run_id: payload.run_id, status: 'running', awaitingApproval: false, awaitingCommittee: null },
      planReady: false,
      plan: null,
      committees: {},
      steps: {},
      gateDecisions: [],
      latestGateDecision: null,
      pendingLeaderQuestions: {},
      agents: {},
      agentReplies: {},
      dialogMessages: [],
      latestEvent: null,
      eventLog: [],
    }
  }

  if (type === 'PLAN_READY') {
    const plan = payload.plan
    const committees = {}
    for (const name of Object.keys(plan.committees || {})) {
      committees[name] = { ...INITIAL_COMMITTEE }
    }
    const ev = { kind: 'plan', text: `Plan ready · ${Object.keys(plan.committees || {}).length} committees`, color: '#3b82f6', ts: Date.now() }
    return { ...state, planReady: true, plan, committees, eventLog: appendLog(state, ev) }
  }

  if (type === 'PLAN_REVISION') {
    const ev = { kind: 'plan', text: 'Plan revision requested', color: '#f97316', ts: Date.now() }
    return { ...state, planReady: false, eventLog: appendLog(state, ev) }
  }

  if (type === 'ENGAGEMENT_STARTED') {
    const ev = { kind: 'engagement', text: 'Engagement started', color: '#22c55e', ts: Date.now() }
    return { ...state, engagement: { ...state.engagement, status: 'running' }, eventLog: appendLog(state, ev) }
  }

  if (type === 'ENGAGEMENT_COMPLETED') {
    const ev = { kind: 'done', text: 'Engagement complete', color: '#e2e8f0', ts: Date.now() }
    return {
      ...state,
      engagement: { ...state.engagement, status: 'completed' },
      latestEvent: ev,
      eventLog: appendLog(state, ev),
    }
  }

  if (type === 'ENGAGEMENT_REJECTED') {
    const ev = { kind: 'engagement', text: `Engagement rejected${payload.reason ? ` · ${payload.reason}` : ''}`, color: '#ef4444', ts: Date.now() }
    return {
      ...state,
      engagement: { ...state.engagement, status: 'rejected', awaitingApproval: false, awaitingCommittee: null },
      eventLog: appendLog(state, ev),
    }
  }

  if (type === 'GATE_AWAITING_APPROVAL') {
    const ev = { kind: 'committee', text: `gate · awaiting approval after ${payload.committee}`, color: '#3b82f6', ts: Date.now() }
    return {
      ...state,
      engagement: { ...state.engagement, awaitingApproval: true, awaitingCommittee: payload.committee },
      latestEvent: ev,
      eventLog: appendLog(state, ev),
    }
  }

  if (type === 'ENGAGEMENT_APPROVED') {
    return {
      ...state,
      engagement: { ...state.engagement, awaitingApproval: false, awaitingCommittee: null },
    }
  }

  if (type === 'COMMITTEE_STARTED') {
    const { committee } = payload
    const prev = state.committees[committee] || INITIAL_COMMITTEE
    const ev = { kind: 'committee', text: `${committee} started`, color: '#94a3b8', ts: Date.now() }
    return {
      ...state,
      committees: { ...state.committees, [committee]: { ...prev, status: 'active' } },
      latestEvent: ev,
      eventLog: appendLog(state, ev),
    }
  }

  if (type === 'COMMITTEE_COMPLETED') {
    const { committee, digest, incomplete } = payload
    const prev = state.committees[committee] || INITIAL_COMMITTEE
    const ev = { kind: 'committee', text: `${committee} complete${incomplete ? ' (incomplete)' : ''}`, color: '#94a3b8', ts: Date.now() }
    return {
      ...state,
      committees: {
        ...state.committees,
        [committee]: { ...prev, status: 'completed', digest: digest || null, incomplete: !!incomplete },
      },
      latestEvent: ev,
      eventLog: appendLog(state, ev),
    }
  }

  if (type === 'STEP_STARTED') {
    const { committee, step_id, description } = payload
    const prev = state.steps[committee] || []
    const ev = { kind: 'tool', text: `${committee} · ${description}`, color: '#64748b', ts: Date.now() }
    return {
      ...state,
      steps: {
        ...state.steps,
        [committee]: [...prev, { id: step_id, description, status: 'active' }],
      },
      latestEvent: ev,
      eventLog: appendLog(state, ev),
    }
  }

  if (type === 'STEP_COMPLETED') {
    const { committee, step_id } = payload
    const prev = state.steps[committee] || []
    return {
      ...state,
      steps: {
        ...state.steps,
        [committee]: prev.map(s => s.id === step_id ? { ...s, status: 'done' } : s),
      },
    }
  }

  if (type === 'GATE_DECISION') {
    const { committee, decision, rationale, to, next_objective, attempt } = payload
    const entry = { committee, decision, rationale, to, next_objective, attempt, ts: Date.now() }
    const icon = GATE_ICONS[decision] || '·'
    let text = `${icon} ${decision.toUpperCase()}`
    if (to && to !== committee) text += ` → ${to}`
    if (attempt) text += ` (${attempt})`
    if (rationale) text += `  ·  ${rationale.slice(0, 80)}`
    const ev = { kind: 'gate', text, color: GATE_COLORS[decision] || '#94a3b8', ts: Date.now() }
    return {
      ...state,
      gateDecisions: [...state.gateDecisions, entry],
      latestGateDecision: entry,
      latestEvent: ev,
      eventLog: appendLog(state, ev),
    }
  }

  if (type === 'LEADER_QUESTION') {
    const { committee, question } = payload
    const ev = { kind: 'committee', text: `${committee} asks: ${question.slice(0, 60)}`, color: '#94a3b8', ts: Date.now() }
    return {
      ...state,
      pendingLeaderQuestions: {
        ...state.pendingLeaderQuestions,
        [committee]: { question, ts: Date.now() },
      },
      latestEvent: ev,
      eventLog: appendLog(state, ev),
    }
  }

  if (type === 'LEADER_QUESTION_ANSWERED') {
    const { committee } = payload
    const next = { ...state.pendingLeaderQuestions }
    delete next[committee]
    return { ...state, pendingLeaderQuestions: next }
  }

  if (type === 'AGENT_SPAWNED') {
    const { agent_id, committee, title, role } = payload
    const ev = { kind: 'spawned', text: `${title} online`, color: '#22c55e', committee, ts: Date.now() }
    return {
      ...state,
      agents: {
        ...state.agents,
        [agent_id]: { id: agent_id, committee, title, role: role || 'specialist', status: 'active', findings: [], classification: null, lastTool: null, toolHistory: [], messageLog: [] },
      },
      latestEvent: ev,
      eventLog: appendLog(state, ev),
    }
  }

  if (type === 'AGENT_SPUN_DOWN') {
    const { agent_id } = payload
    if (!state.agents[agent_id]) return state
    return {
      ...state,
      agents: { ...state.agents, [agent_id]: { ...state.agents[agent_id], status: 'spun_down' } },
    }
  }

  if (type === 'AGENT_TOOL_CALLED') {
    const { agent_id, tool, input_summary } = payload
    if (!state.agents[agent_id]) return state
    const entry = { kind: 'tool', tool, input_summary, ts: Date.now() }
    const prev = state.agents[agent_id]
    const agentTitle = prev.title || agent_id.split('.').pop()
    const callStr = formatToolSummary(tool, input_summary)
    const ev = { kind: 'tool', text: `${agentTitle} · ${callStr}`, color: '#64748b', committee: prev.committee, ts: Date.now() }
    return {
      ...state,
      agents: {
        ...state.agents,
        [agent_id]: {
          ...prev,
          lastTool: entry,
          toolHistory: [...(prev.toolHistory || []), entry].slice(-20),
          messageLog: [...(prev.messageLog || []).slice(-(MESSAGE_LOG_MAX - 1)), entry],
        },
      },
      latestEvent: ev,
      eventLog: appendLog(state, ev),
    }
  }

  if (type === 'AGENT_MODEL_TEXT') {
    const { agent_id, text, stop_reason } = payload
    if (!state.agents[agent_id]) return state
    const entry = { kind: 'text', text, stop_reason, ts: Date.now() }
    const prev = state.agents[agent_id]
    return {
      ...state,
      agents: {
        ...state.agents,
        [agent_id]: {
          ...prev,
          messageLog: [...(prev.messageLog || []).slice(-(MESSAGE_LOG_MAX - 1)), entry],
        },
      },
    }
  }

  if (type === 'AGENT_FINDING') {
    const { agent_id, committee, classification, summary } = payload
    if (!state.agents[agent_id]) return state
    const finding = { classification, summary, ts: Date.now() }
    const updatedFindings = [...state.agents[agent_id].findings, finding]
    const agentClassification = dominantClassification(updatedFindings)
    const FINDING_LABELS = { signal_critical: 'CRIT', signal_warn: 'WARN', signal_info: 'INFO' }
    const FINDING_COLOR = { signal_critical: '#ef4444', signal_warn: '#f97316', signal_info: '#3b82f6' }
    const label = FINDING_LABELS[classification] || classification

    const committeeUpdate = {}
    if (classification === 'signal_warn' || classification === 'signal_critical') {
      const prev = state.committees[committee] || INITIAL_COMMITTEE
      const committeeFindings = [...(prev.findings || []), finding]
      committeeUpdate[committee] = {
        ...prev,
        badgeCount: (prev.badgeCount || 0) + 1,
        classification: dominantClassification(committeeFindings),
        findings: committeeFindings,
      }
    }

    const ev = { kind: 'finding', text: `${label}  ${summary}`, color: FINDING_COLOR[classification] || '#64748b', classification, committee, ts: Date.now() }
    return {
      ...state,
      agents: {
        ...state.agents,
        [agent_id]: { ...state.agents[agent_id], findings: updatedFindings, classification: agentClassification },
      },
      committees: { ...state.committees, ...committeeUpdate },
      latestEvent: ev,
      eventLog: appendLog(state, ev),
    }
  }

  if (type === 'AGENT_OPERATOR_REPLY') {
    const { agent_id, text } = payload
    const prev = state.agentReplies[agent_id] || []
    return {
      ...state,
      agentReplies: {
        ...state.agentReplies,
        [agent_id]: [...prev, { text, ts: Date.now(), role: 'agent' }],
      },
    }
  }

  if (type === 'ORCHESTRATOR_QUESTION') {
    return {
      ...state,
      dialogMessages: [...state.dialogMessages, { role: 'orch', text: payload.question, ts: Date.now() }],
    }
  }

  if (type === 'ORCHESTRATOR_MESSAGE') {
    return {
      ...state,
      dialogMessages: [...state.dialogMessages, { role: 'orch-msg', text: payload.text, ts: Date.now() }],
    }
  }

  if (type === 'DIALOG_OPERATOR_MESSAGE') {
    return {
      ...state,
      dialogMessages: [...state.dialogMessages, { role: 'oper', text: payload.text, ts: Date.now() }],
    }
  }

  if (type === 'OPEN_CHAT') {
    return {
      ...state,
      chat: {
        isOpen: true,
        agentId: payload.agentId,
        committeeId: payload.committeeId,
        agentTitle: payload.agentTitle,
        findings: payload.findings || [],
        focusFindings: payload.focusFindings || false,
      },
    }
  }

  if (type === 'CLOSE_CHAT') {
    return { ...state, chat: { ...state.chat, isOpen: false } }
  }

  if (type === 'DISMISS_BADGE') {
    const { committee } = payload
    if (!state.committees[committee]) return state
    return {
      ...state,
      committees: { ...state.committees, [committee]: { ...state.committees[committee], badgeCount: 0 } },
    }
  }

  return state
}

const PAGE_TITLES = {
  request: 'athena | start',
  dialog:  'athena | briefing',
  dashboard: 'athena | engagement',
}

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState)

  useEffect(() => {
    document.title = PAGE_TITLES[state.page] || 'athena'
  }, [state.page])

  const handleEvent = useCallback((event) => {
    const { topic, ...payload } = event
    if (topic === 'engagement.started')      dispatch({ type: 'ENGAGEMENT_STARTED', payload })
    if (topic === 'engagement.completed')    dispatch({ type: 'ENGAGEMENT_COMPLETED', payload })
    if (topic === 'engagement.rejected')     dispatch({ type: 'ENGAGEMENT_REJECTED', payload })
    if (topic === 'engagement.plan_ready')   dispatch({ type: 'PLAN_READY', payload })
    if (topic === 'gate.awaiting_approval')  dispatch({ type: 'GATE_AWAITING_APPROVAL', payload })
    if (topic === 'engagement.approved')     dispatch({ type: 'ENGAGEMENT_APPROVED', payload })
    if (topic === 'committee.started')       dispatch({ type: 'COMMITTEE_STARTED', payload })
    if (topic === 'committee.completed')     dispatch({ type: 'COMMITTEE_COMPLETED', payload })
    if (topic === 'step.started')            dispatch({ type: 'STEP_STARTED', payload })
    if (topic === 'step.completed')          dispatch({ type: 'STEP_COMPLETED', payload })
    if (topic === 'gate.decision')           dispatch({ type: 'GATE_DECISION', payload })
    if (topic === 'committee.ask_operator')  dispatch({ type: 'LEADER_QUESTION', payload })
    if (topic === 'agent.spawned')           dispatch({ type: 'AGENT_SPAWNED', payload })
    if (topic === 'agent.spun_down')         dispatch({ type: 'AGENT_SPUN_DOWN', payload })
    if (topic === 'agent.tool_called')       dispatch({ type: 'AGENT_TOOL_CALLED', payload })
    if (topic === 'agent.model_text')        dispatch({ type: 'AGENT_MODEL_TEXT', payload })
    if (topic === 'agent.finding')           dispatch({ type: 'AGENT_FINDING', payload })
    if (topic === 'agent.operator_reply')    dispatch({ type: 'AGENT_OPERATOR_REPLY', payload })
    if (topic === 'orchestrator.question')    dispatch({ type: 'ORCHESTRATOR_QUESTION', payload })
    if (topic === 'orchestrator.message')     dispatch({ type: 'ORCHESTRATOR_MESSAGE', payload })
    if (topic === 'engagement.plan_revision') dispatch({ type: 'PLAN_REVISION', payload })
  }, [])

  useEvents(state.engagement.run_id, handleEvent)

  if (state.page === 'request') {
    return (
      <EngagementRequest
        onSubmit={(run_id) => dispatch({ type: 'RUN_STARTED', payload: { run_id } })}
      />
    )
  }

  if (state.page === 'dialog') {
    return <OrchestratorDialog state={state} dispatch={dispatch} />
  }

  return <Dashboard state={state} dispatch={dispatch} />
}
