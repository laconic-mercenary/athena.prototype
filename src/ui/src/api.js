const BASE = ''

async function _json(resp) {
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(`${resp.status}: ${text}`)
  }
  return resp.json()
}

export async function startEngagement(instructions) {
  return _json(await fetch(`${BASE}/engagements`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ instructions }),
  }))
}

export async function getEngagement(runId) {
  return _json(await fetch(`${BASE}/engagements/${runId}`))
}

// Demo Restart: abandon the current run so a fresh one can start. Idempotent server-side.
export async function abortEngagement(runId) {
  const resp = await fetch(`${BASE}/engagements/${runId}/abort`, { method: 'POST' })
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
}

export async function sendChat(runId, target, message) {
  const resp = await fetch(`${BASE}/engagements/${runId}/chat/${target}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
}

export async function listArtifacts(runId) {
  return _json(await fetch(`${BASE}/engagements/${runId}/artifacts`))
}

export async function getArtifact(runId, name, { render = false } = {}) {
  const q = render ? '?render=true' : ''
  const resp = await fetch(`${BASE}/engagements/${runId}/artifacts/${name}${q}`)
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
  return resp.text()
}

export async function planReview(runId, action, collaborator, planText) {
  return _json(await fetch(`${BASE}/engagements/${runId}/plan-review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      action,
      collaborator: collaborator || null,
      plan_text: planText || null,
    }),
  }))
}

export async function gateDecision(runId, action, suggestion, collaborator) {
  return _json(await fetch(`${BASE}/engagements/${runId}/gate-decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, suggestion: suggestion || null, collaborator: collaborator || null }),
  }))
}

// Send a follow-up message to the collaborator parked on a committee gate. The gate stays
// parked; the thread continues until the collaborator replies APPROVE.
export async function collaboratorMessage(runId, message) {
  return _json(await fetch(`${BASE}/engagements/${runId}/collaborator-message`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  }))
}

// In-loop gate (element / step / tool). action is kind-specific:
//   element: "accept" / "override" (winnerId) / "redo"
//   step:    "accept" / "redo" (suggestion) / "skip"
//   tool:    "approve" / "deny" (suggestion = reason)
// See HARNESS.md.
export async function loopGateDecision(runId, action, winnerId, suggestion) {
  return _json(await fetch(`${BASE}/engagements/${runId}/loop-gate-decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, winner_id: winnerId || null, suggestion: suggestion || null }),
  }))
}

// Arm / disarm an in-loop gate kind for a committee. Runtime observation mode —
// takes effect on the next matching tool call (forward-only).
export async function loopGateArm(runId, committee, kind, armed) {
  return _json(await fetch(`${BASE}/engagements/${runId}/loop-gate-arm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ committee, kind, armed }),
  }))
}

export async function getManifestSummary(runId) {
  return _json(await fetch(`${BASE}/engagements/${runId}/manifest-summary`))
}

export async function setSpecialistEnabled(runId, key, enabled) {
  return _json(await fetch(`${BASE}/engagements/${runId}/specialist-config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, enabled }),
  }))
}

export async function reportChat(runId, message) {
  return _json(await fetch(`${BASE}/engagements/${runId}/report-chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  }))
}

export async function revealArtifact(runId, name) {
  const resp = await fetch(`${BASE}/engagements/${runId}/artifacts/${name}/reveal`, {
    method: 'POST',
  })
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
}
