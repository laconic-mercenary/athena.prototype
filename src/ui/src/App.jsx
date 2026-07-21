import { useReducer, useCallback, useEffect } from 'react'
import { useEvents } from './useEvents'
import { EngagementRequest } from './pages/EngagementRequest'
import { OrchestratorDialog } from './pages/OrchestratorDialog'
import { Dashboard } from './pages/Dashboard'
import './index.css'

const COMMITTEES = ['recon', 'planning', 'retrieval', 'reporting']

const INITIAL_COMMITTEE = { status: 'inactive', classification: null, badgeCount: 0, findings: [], artifactReady: false }

const initialState = {
  page: 'request',
  engagement: { run_id: null, status: 'idle', target: null, notes: null, awaitingApproval: false },
  committees: Object.fromEntries(COMMITTEES.map(c => [c, { ...INITIAL_COMMITTEE, findings: [] }])),
  agents: {},
  agentReplies: {},
  dialogMessages: [],
  chat: { isOpen: false, agentId: null, agentTitle: null, findings: [] },
  latestEvent: null,
}

// Returns the highest-severity classification from a list of findings.
function dominantClassification(findings) {
  const ORDER = ['signal_critical', 'signal_warn', 'signal_info', 'noise', 'unknown']
  for (const cls of ORDER) {
    if (findings.some(f => f.classification === cls)) return cls
  }
  return null
}

function reducer(state, action) {
  const { type, payload } = action

  if (type === 'NAVIGATE') {
    return { ...state, page: payload }
  }

  if (type === 'ENGAGEMENT_STARTED') {
    return {
      ...state,
      page: 'dashboard',
      engagement: { ...state.engagement, status: 'running', target: payload.target, notes: payload.notes },
    }
  }

  if (type === 'ENGAGEMENT_COMPLETED') {
    return {
      ...state,
      engagement: { ...state.engagement, status: 'completed' },
      latestEvent: { kind: 'done', text: 'Engagement complete', ts: Date.now() },
    }
  }

  if (type === 'ENGAGEMENT_REJECTED') {
    return { ...state, engagement: { ...state.engagement, status: 'rejected', awaitingApproval: false } }
  }

  if (type === 'AWAITING_APPROVAL') {
    return {
      ...state,
      engagement: { ...state.engagement, awaitingApproval: true },
      latestEvent: { kind: 'committee', text: 'Planning complete — awaiting operator approval', ts: Date.now() },
    }
  }

  if (type === 'ENGAGEMENT_APPROVED') {
    return {
      ...state,
      engagement: { ...state.engagement, awaitingApproval: false },
      latestEvent: { kind: 'committee', text: 'Retrieval phase approved', ts: Date.now() },
    }
  }

  if (type === 'RUN_STARTED') {
    // Fired immediately when engagement is submitted; wait on dialog page for orchestrator briefing
    return {
      ...state,
      page: 'dialog',
      engagement: { ...state.engagement, run_id: payload.run_id, status: 'running', awaitingApproval: false },
      committees: initialState.committees,
      agents: {},
      agentReplies: {},
      dialogMessages: [],
      latestEvent: null,
    }
  }

  if (type === 'COMMITTEE_STARTED') {
    const { committee } = payload
    if (!state.committees[committee]) return state
    return {
      ...state,
      committees: {
        ...state.committees,
        [committee]: { ...state.committees[committee], status: 'active' },
      },
      latestEvent: { kind: 'committee', text: `${committee} committee started`, ts: Date.now() },
    }
  }

  if (type === 'COMMITTEE_COMPLETED') {
    const { committee } = payload
    if (!state.committees[committee]) return state
    return {
      ...state,
      committees: {
        ...state.committees,
        [committee]: { ...state.committees[committee], status: 'completed' },
      },
      latestEvent: { kind: 'committee', text: `${committee} committee complete`, ts: Date.now() },
    }
  }

  if (type === 'COMMITTEE_ARTIFACT_EMITTED') {
    // Fired after the committee's .md is written to disk — gate report buttons on
    // this (not COMMITTEE_COMPLETED, which fires before the file exists).
    const { committee } = payload
    if (!state.committees[committee]) return state
    return {
      ...state,
      committees: {
        ...state.committees,
        [committee]: { ...state.committees[committee], artifactReady: true },
      },
    }
  }

  if (type === 'AGENT_SPAWNED') {
    const { agent_id, committee, title } = payload
    return {
      ...state,
      agents: {
        ...state.agents,
        [agent_id]: { id: agent_id, committee, title, status: 'active', findings: [], lastTool: null, toolHistory: [] },
      },
      latestEvent: { kind: 'spawned', text: `${title} online`, committee, ts: Date.now() },
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
    const entry = { tool, input_summary, ts: Date.now() }
    const prev = state.agents[agent_id]
    const agentTitle = prev.title || agent_id.split('.').pop()
    const summary = input_summary ? `${tool}  ${input_summary}` : tool
    return {
      ...state,
      agents: {
        ...state.agents,
        [agent_id]: {
          ...prev,
          lastTool: entry,
          toolHistory: [...(prev.toolHistory || []), entry].slice(-20),
        },
      },
      latestEvent: { kind: 'tool', text: `${agentTitle} › ${summary}`, committee: prev.committee, ts: Date.now() },
    }
  }

  if (type === 'AGENT_FINDING') {
    const { agent_id, committee, classification, summary } = payload
    if (!state.agents[agent_id]) return state
    const finding = { classification, summary, ts: Date.now() }
    const updatedFindings = [...state.agents[agent_id].findings, finding]
    const agentClassification = dominantClassification(updatedFindings)

    const FINDING_LABELS = { signal_critical: 'CRIT', signal_warn: 'WARN', signal_info: 'INFO' }
    const label = FINDING_LABELS[classification] || classification

    // Escalate committee badge count on warn/critical
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

    return {
      ...state,
      agents: {
        ...state.agents,
        [agent_id]: { ...state.agents[agent_id], findings: updatedFindings, classification: agentClassification },
      },
      committees: { ...state.committees, ...committeeUpdate },
      latestEvent: { kind: 'finding', text: `${label}  ${summary}`, classification, committee, ts: Date.now() },
    }
  }

  if (type === 'ORCHESTRATOR_QUESTION') {
    return {
      ...state,
      page: 'dialog',
      dialogMessages: [...state.dialogMessages, { role: 'orch', text: payload.question, ts: Date.now() }],
    }
  }

  if (type === 'DIALOG_OPERATOR_MESSAGE') {
    return {
      ...state,
      dialogMessages: [...state.dialogMessages, { role: 'oper', text: payload.text, ts: Date.now(), isConfirm: payload.isConfirm || false }],
    }
  }

  if (type === 'ORCHESTRATOR_ANSWER') {
    return state
  }

  if (type === 'OPEN_CHAT') {
    return { ...state, chat: { isOpen: true, agentId: payload.agentId, agentTitle: payload.agentTitle, findings: payload.findings || [], focusFindings: payload.focusFindings || false } }
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

  return state
}

const PAGE_TITLES = {
  request:   'athena | start',
  dialog:    'athena | briefing',
  dashboard: 'athena | engagement',
}

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState)

  useEffect(() => {
    document.title = PAGE_TITLES[state.page] || 'athena'
  }, [state.page])

  const handleEvent = useCallback((event) => {
    const { topic, ...payload } = event
    if (topic === 'engagement.started')   dispatch({ type: 'ENGAGEMENT_STARTED', payload })
    if (topic === 'engagement.completed') dispatch({ type: 'ENGAGEMENT_COMPLETED', payload })
    if (topic === 'engagement.rejected')  dispatch({ type: 'ENGAGEMENT_REJECTED', payload })
    if (topic === 'committee.started')    dispatch({ type: 'COMMITTEE_STARTED', payload })
    if (topic === 'committee.completed')  dispatch({ type: 'COMMITTEE_COMPLETED', payload })
    if (topic === 'committee.artifact_emitted') dispatch({ type: 'COMMITTEE_ARTIFACT_EMITTED', payload })
    if (topic === 'agent.spawned')        dispatch({ type: 'AGENT_SPAWNED', payload })
    if (topic === 'agent.spun_down')      dispatch({ type: 'AGENT_SPUN_DOWN', payload })
    if (topic === 'agent.tool_called')    dispatch({ type: 'AGENT_TOOL_CALLED', payload })
    if (topic === 'agent.finding')         dispatch({ type: 'AGENT_FINDING', payload })
    if (topic === 'agent.operator_reply')       dispatch({ type: 'AGENT_OPERATOR_REPLY', payload })
    if (topic === 'engagement.awaiting_approval') dispatch({ type: 'AWAITING_APPROVAL', payload })
    if (topic === 'engagement.approved')          dispatch({ type: 'ENGAGEMENT_APPROVED', payload })
    if (topic === 'orchestrator.question') dispatch({ type: 'ORCHESTRATOR_QUESTION', payload })
    if (topic === 'orchestrator.answer')   dispatch({ type: 'ORCHESTRATOR_ANSWER', payload })
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
    return (
      <OrchestratorDialog
        state={state}
        dispatch={dispatch}
      />
    )
  }

  return (
    <Dashboard
      state={state}
      dispatch={dispatch}
    />
  )
}
