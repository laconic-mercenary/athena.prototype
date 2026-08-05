import { useReducer, useCallback, useEffect } from 'react'
import { useEvents } from './useEvents'
import { EngagementRequest } from './pages/EngagementRequest'
import { OrchestratorDialog } from './pages/OrchestratorDialog'
import { Dashboard } from './pages/Dashboard'
import { AcceptanceBanner } from './components/AcceptanceBanner'
import { getManifestSummary, setSpecialistEnabled } from './api'
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

const ORCHESTRATOR_AGENT_ID = 'athena.orchestrator'

function createInitialState() {
  return {
  page: 'request',
  engagement: {
    run_id: null,
    status: 'idle',
    awaitingApproval: false,
    awaitingCommittee: null,
    awaitingRedoAvailable: false,
  },
  planReady: false,
  plan: null,
  committees: {},
  steps: {},
  // In-loop operator gate (element / step / tool). awaiting is true while a leader
  // is blocked waiting for the operator's decision on a single tool call.
  loopGate: { awaiting: false, kind: null, committee: null, payload: null },
  armedGates: {},   // committee -> { element?: true, step?: true, tool?: true }
  gateDecisions: [],
  latestGateDecision: null,
  pendingLeaderQuestions: {},
  pendingOrchestratorQuestion: null,
  collaboratorPending: null,   // { alias, sentAt } while waiting for email co-approval
  collaboratorReply: null,     // { alias, decision, message, ts } — collaborator's latest reply
  collaboratorThread: [],      // committee-gate email thread: [{ role:'operator'|'collaborator', alias?, decision?, message, ts }]
  manifestSummary: null,       // { committees: [{name, elements: [{id, label, specialists: [{id, title, skills}]}]}] }
  disabledSpecialists: {},     // key -> true for disabled specialists
  agents: {},
  agentReplies: {},
  dialogMessages: [],
  chat: { isOpen: false, agentId: null, committeeId: null, agentTitle: null, findings: [], focusFindings: false },
  latestEvent: null,
  eventLog: [],
  }
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

  // Demo Restart: throw away all engagement state and return to the start screen.
  if (type === 'RESET') return createInitialState()

  if (type === 'RUN_STARTED') {
    return {
      ...state,
      page: 'dialog',
      engagement: { run_id: payload.run_id, status: 'running', awaitingApproval: false, awaitingCommittee: null, awaitingRedoAvailable: false, objective: payload.objective || '', startedAt: Date.now() },
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
      collaboratorPending: null,
      collaboratorReply: null,
      collaboratorThread: [],
      manifestSummary: null,
      disabledSpecialists: {},
      latestEvent: null,
      eventLog: [],
    }
  }

  if (type === 'MANIFEST_SUMMARY') {
    return { ...state, manifestSummary: payload }
  }

  if (type === 'TOGGLE_SPECIALIST') {
    const { key, enabled } = payload
    const next = { ...state.disabledSpecialists }
    if (enabled) delete next[key]
    else next[key] = true
    return { ...state, disabledSpecialists: next }
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

  // Switch-panel fallback: a revision was requested but no new plan arrived in time
  // (orchestrator answered conversationally, was slow, or the response dropped). Restore
  // the ready state on the existing plan so the panel can't wedge disabled forever.
  if (type === 'PLAN_REVISION_TIMEOUT') {
    return state.plan ? { ...state, planReady: true } : state
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
    const ev = { kind: 'committee', text: `gate · awaiting decision after ${payload.committee}`, color: '#3b82f6', ts: Date.now() }
    return {
      ...state,
      engagement: {
        ...state.engagement,
        awaitingApproval: true,
        awaitingCommittee: payload.committee,
        awaitingRedoAvailable: payload.redo_available !== false,
      },
      latestEvent: ev,
      eventLog: appendLog(state, ev),
    }
  }

  if (type === 'ENGAGEMENT_APPROVED' || type === 'GATE_RESOLVED') {
    return {
      ...state,
      collaboratorPending: null,
      collaboratorThread: [],
      engagement: { ...state.engagement, awaitingApproval: false, awaitingCommittee: null, awaitingRedoAvailable: false },
    }
  }

  if (type === 'COLLABORATOR_PENDING') {
    const ev = { kind: 'collab', text: `Co-approval sent · awaiting @${payload.alias}`, color: '#8b5cf6', ts: Date.now() }
    return {
      ...state,
      collaboratorPending: { alias: payload.alias, sentAt: payload.sent_at },
      collaboratorThread: [],
      eventLog: appendLog(state, ev),
    }
  }

  if (type === 'OPERATOR_COLLAB_MESSAGE') {
    // The operator sent a follow-up email to the collaborator; echo it into the thread.
    const { message } = payload
    const ev = { kind: 'collab', text: `you → @${payload.alias || 'collaborator'}`, color: '#8b5cf6', ts: Date.now() }
    return {
      ...state,
      collaboratorThread: [...state.collaboratorThread, { role: 'operator', message, ts: Date.now() }],
      eventLog: appendLog(state, ev),
    }
  }

  if (type === 'COLLABORATOR_REPLIED') {
    // The collaborator answered by email. Show their words in the relevant chat
    // (committee-gate → that leader's chat; plan-gate → orchestrator chat), and stash
    // the reply so the gate modal can display the decision and self-close after a beat.
    const { alias, kind, committee, decision, message } = payload
    const label = decision === 'comment' ? 'message' : decision
    const ev = { kind: 'collab', text: `@${alias} · ${label}`, color: '#8b5cf6', ts: Date.now() }
    const chatMsg = { text: message || `(${label})`, ts: Date.now(), role: 'collaborator', alias, decision }

    let agentReplies = state.agentReplies
    let dialogMessages = state.dialogMessages
    if (kind === 'committee' && committee) {
      const leaderId = Object.keys(state.agents).find(
        id => state.agents[id].committee === committee && state.agents[id].role === 'leader'
      )
      if (leaderId) {
        agentReplies = { ...agentReplies, [leaderId]: [...(agentReplies[leaderId] || []), chatMsg] }
      }
    } else {
      dialogMessages = [...dialogMessages, { role: 'collab', text: message || `(${label})`, ts: Date.now(), alias }]
      agentReplies = { ...agentReplies, [ORCHESTRATOR_AGENT_ID]: [...(agentReplies[ORCHESTRATOR_AGENT_ID] || []), chatMsg] }
    }
    const collaboratorThread = kind === 'committee'
      ? [...state.collaboratorThread, { role: 'collaborator', alias, decision, message, ts: Date.now() }]
      : state.collaboratorThread
    return {
      ...state,
      agentReplies,
      dialogMessages,
      collaboratorThread,
      collaboratorReply: { alias, decision, message, kind, committee, ts: Date.now() },
      latestEvent: ev,
      eventLog: appendLog(state, ev),
    }
  }

  if (type === 'CLEAR_COLLAB_REPLY') {
    return { ...state, collaboratorReply: null, collaboratorThread: [], collaboratorPending: null }
  }

  if (type === 'LOOP_GATE_AWAITING') {
    // The event carries a nested `payload` (kind-specific body, e.g. element variants).
    const { kind, committee, payload: body } = payload
    const ev = { kind: 'committee', text: `${kind} gate · awaiting decision in ${committee}`, color: '#3b82f6', ts: Date.now() }
    return {
      ...state,
      loopGate: { awaiting: true, kind, committee, payload: body || null },
      latestEvent: ev,
      eventLog: appendLog(state, ev),
    }
  }

  if (type === 'LOOP_GATE_RESOLVED') {
    return {
      ...state,
      loopGate: { awaiting: false, kind: null, committee: null, payload: null },
    }
  }

  if (type === 'GATE_ARMED') {
    const { committee, kind, armed } = payload
    const prev = state.armedGates[committee] || {}
    const next = { ...prev }
    if (armed) next[kind] = true
    else delete next[kind]
    return { ...state, armedGates: { ...state.armedGates, [committee]: next } }
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

  if (type === 'COMMITTEE_RESULT_SELECTED') {
    const { committee, element_id, winner_id, winner_title, rationale, result, variants } = payload
    const prev = state.committees[committee] || INITIAL_COMMITTEE
    return {
      ...state,
      committees: {
        ...state.committees,
        [committee]: {
          ...prev,
          elementResults: {
            ...(prev.elementResults || {}),
            [element_id]: { winnerId: winner_id, winnerTitle: winner_title, rationale, result, variants: variants || [] },
          },
        },
      },
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
    const { committee, decision, rationale, to, next_objective, attempt, decided_by } = payload
    const entry = { committee, decision, rationale, to, next_objective, attempt, decidedBy: decided_by, ts: Date.now() }
    const icon = GATE_ICONS[decision] || '·'
    let text = `${icon} ${decision.toUpperCase()}`
    if (to && to !== committee) text += ` → ${to}`
    if (attempt) text += ` (${attempt})`
    if (rationale) text += `  ·  ${rationale.slice(0, 80)}`
    const ev = { kind: 'gate', text, color: GATE_COLORS[decision] || '#94a3b8', ts: Date.now() }
    // A gate decision means the gate is no longer awaiting — clear the awaiting/pending
    // state so the committee-gate modal closes, including when a collaborator's co-approval
    // (not the operator's own click) is what released it.
    return {
      ...state,
      gateDecisions: [...state.gateDecisions, entry],
      latestGateDecision: entry,
      latestEvent: ev,
      eventLog: appendLog(state, ev),
      collaboratorPending: null,
      engagement: { ...state.engagement, awaitingApproval: false, awaitingCommittee: null, awaitingRedoAvailable: false },
    }
  }

  if (type === 'LEADER_QUESTION') {
    const { committee, question } = payload
    const ev = { kind: 'committee', text: `${committee} asks: ${question.slice(0, 60)}`, color: '#94a3b8', ts: Date.now() }
    const leaderId = Object.keys(state.agents).find(
      id => state.agents[id].committee === committee && state.agents[id].role === 'leader'
    )
    const agentReplies = leaderId
      ? {
          ...state.agentReplies,
          [leaderId]: [...(state.agentReplies[leaderId] || []), { text: question, ts: Date.now(), role: 'agent' }],
        }
      : state.agentReplies
    return {
      ...state,
      pendingLeaderQuestions: {
        ...state.pendingLeaderQuestions,
        [committee]: { question, ts: Date.now() },
      },
      agentReplies,
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
    const { agent_id, committee, title, role, element_id, element_label, variant_label } = payload
    const ev = { kind: 'spawned', text: `${title} online`, color: '#22c55e', committee, ts: Date.now() }
    return {
      ...state,
      agents: {
        ...state.agents,
        [agent_id]: { id: agent_id, committee, title, role: role || 'specialist', element_id: element_id || null, element_label: element_label || element_id || null, variant_label: variant_label || null, status: 'active', findings: [], classification: null, lastTool: null, toolHistory: [], messageLog: [] },
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

  if (type === 'AGENT_FAILED') {
    // A compare-mode specialist raised and was dropped from the comparison. Mark its box
    // failed and stash the error so the graph can flag it (red border + warning tooltip).
    const { agent_id, error } = payload
    if (!state.agents[agent_id]) return state
    const ev = { kind: 'failed', text: `${state.agents[agent_id].title} failed`, color: '#ef4444', committee: payload.committee, ts: Date.now() }
    return {
      ...state,
      agents: { ...state.agents, [agent_id]: { ...state.agents[agent_id], status: 'failed', error: error || 'Specialist failed' } },
      latestEvent: ev,
      eventLog: appendLog(state, ev),
    }
  }

  if (type === 'AGENT_TOOL_CALLED') {
    const { agent_id, tool, input_summary, call_id } = payload
    if (!state.agents[agent_id]) return state
    const entry = { kind: 'tool', tool, input_summary, call_id, ts: Date.now() }
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

  if (type === 'OPERATOR_MESSAGE') {
    // Thread an operator's outgoing chat into the target agent's log. Prefer the
    // exact agent; fall back to the committee's leader when only a committee is known.
    const { committeeId, agentId, text } = payload
    const targetId = (agentId && state.agents[agentId])
      ? agentId
      : Object.keys(state.agents).find(
          id => state.agents[id].committee === committeeId && state.agents[id].role === 'leader'
        )
    if (!targetId || !state.agents[targetId]) return state
    const prev = state.agents[targetId]
    const entry = { kind: 'operator', text, ts: Date.now() }
    return {
      ...state,
      agents: {
        ...state.agents,
        [targetId]: {
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

  if (type === 'AGENT_TOOL_RESULT') {
    const { agent_id, call_id, result } = payload
    if (!state.agents[agent_id]) return state
    const prev = state.agents[agent_id]
    const updatedToolHistory = (prev.toolHistory || []).map(entry =>
      entry.call_id === call_id ? { ...entry, result } : entry
    )
    return {
      ...state,
      agents: {
        ...state.agents,
        [agent_id]: { ...prev, toolHistory: updatedToolHistory },
      },
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
    const prev = state.agentReplies[ORCHESTRATOR_AGENT_ID] || []
    return {
      ...state,
      pendingOrchestratorQuestion: payload.question,
      dialogMessages: [...state.dialogMessages, { role: 'orch', text: payload.question, ts: Date.now() }],
      agentReplies: {
        ...state.agentReplies,
        [ORCHESTRATOR_AGENT_ID]: [...prev, { text: payload.question, ts: Date.now(), role: 'agent' }],
      },
    }
  }

  if (type === 'ORCHESTRATOR_ANSWERED') {
    return { ...state, pendingOrchestratorQuestion: null }
  }

  if (type === 'ORCHESTRATOR_MESSAGE') {
    const prev = state.agentReplies[ORCHESTRATOR_AGENT_ID] || []
    return {
      ...state,
      dialogMessages: [...state.dialogMessages, { role: 'orch-msg', text: payload.text, ts: Date.now() }],
      agentReplies: {
        ...state.agentReplies,
        [ORCHESTRATOR_AGENT_ID]: [...prev, { text: payload.text, ts: Date.now(), role: 'agent' }],
      },
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
  const [state, dispatch] = useReducer(reducer, undefined, createInitialState)

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
    if (topic === 'engagement.approved') {
      dispatch({ type: 'ENGAGEMENT_APPROVED', payload })
      // Navigate to dashboard on approval — covers both normal and collaborator paths.
      // Normal flow already navigated in handleProceed; dispatching again is a no-op.
      dispatch({ type: 'NAVIGATE', payload: 'dashboard' })
    }
    if (topic === 'committee.started')       dispatch({ type: 'COMMITTEE_STARTED', payload })
    if (topic === 'committee.completed')     dispatch({ type: 'COMMITTEE_COMPLETED', payload })
    if (topic === 'step.started')            dispatch({ type: 'STEP_STARTED', payload })
    if (topic === 'step.completed')          dispatch({ type: 'STEP_COMPLETED', payload })
    if (topic === 'gate.decision')           dispatch({ type: 'GATE_DECISION', payload })
    if (topic === 'committee.ask_operator')  dispatch({ type: 'LEADER_QUESTION', payload })
    if (topic === 'committee.operator_replied') dispatch({ type: 'LEADER_QUESTION_ANSWERED', payload })
    if (topic === 'agent.spawned')           dispatch({ type: 'AGENT_SPAWNED', payload })
    if (topic === 'agent.spun_down')         dispatch({ type: 'AGENT_SPUN_DOWN', payload })
    if (topic === 'agent.failed')            dispatch({ type: 'AGENT_FAILED', payload })
    if (topic === 'agent.tool_called')       dispatch({ type: 'AGENT_TOOL_CALLED', payload })
    if (topic === 'agent.tool_result')       dispatch({ type: 'AGENT_TOOL_RESULT', payload })
    if (topic === 'agent.model_text')        dispatch({ type: 'AGENT_MODEL_TEXT', payload })
    if (topic === 'agent.finding')           dispatch({ type: 'AGENT_FINDING', payload })
    if (topic === 'agent.operator_reply')    dispatch({ type: 'AGENT_OPERATOR_REPLY', payload })
    if (topic === 'committee.result_selected') dispatch({ type: 'COMMITTEE_RESULT_SELECTED', payload })
    if (topic === 'loop_gate.awaiting')       dispatch({ type: 'LOOP_GATE_AWAITING', payload })
    if (topic === 'loop_gate.resolved')       dispatch({ type: 'LOOP_GATE_RESOLVED', payload })
    if (topic === 'orchestrator.question')    dispatch({ type: 'ORCHESTRATOR_QUESTION', payload })
    if (topic === 'orchestrator.answer')      dispatch({ type: 'ORCHESTRATOR_ANSWERED', payload })
    if (topic === 'orchestrator.message')     dispatch({ type: 'ORCHESTRATOR_MESSAGE', payload })
    if (topic === 'engagement.plan_revision') dispatch({ type: 'PLAN_REVISION', payload })
    if (topic === 'engagement.collaborator_pending') dispatch({ type: 'COLLABORATOR_PENDING', payload })
    if (topic === 'collaborator.replied')             dispatch({ type: 'COLLABORATOR_REPLIED', payload })
    if (topic === 'collaborator.operator_message')    dispatch({ type: 'OPERATOR_COLLAB_MESSAGE', payload })
  }, [])

  useEvents(state.engagement.run_id, handleEvent)

  // Fetch manifest summary once when a run_id is assigned.
  useEffect(() => {
    const runId = state.engagement.run_id
    if (!runId) return
    let cancelled = false
    getManifestSummary(runId)
      .then(summary => { if (!cancelled) dispatch({ type: 'MANIFEST_SUMMARY', payload: summary }) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [state.engagement.run_id])

  async function handleToggleSpecialist(runId, key, enabled) {
    dispatch({ type: 'TOGGLE_SPECIALIST', payload: { key, enabled } })
    try {
      await setSpecialistEnabled(runId, key, enabled)
    } catch {
      // Revert on failure
      dispatch({ type: 'TOGGLE_SPECIALIST', payload: { key, enabled: !enabled } })
    }
  }

  if (state.page === 'request') {
    return (
      <>
        <AcceptanceBanner />
        <EngagementRequest
          onSubmit={(run_id, objective) => dispatch({ type: 'RUN_STARTED', payload: { run_id, objective } })}
        />
      </>
    )
  }

  if (state.page === 'dialog') {
    return (
      <>
        <AcceptanceBanner />
        <OrchestratorDialog
          state={state}
          dispatch={dispatch}
          onToggleSpecialist={handleToggleSpecialist}
        />
      </>
    )
  }

  return (
    <>
      <AcceptanceBanner />
      <Dashboard state={state} dispatch={dispatch} onToggleSpecialist={handleToggleSpecialist} />
    </>
  )
}
