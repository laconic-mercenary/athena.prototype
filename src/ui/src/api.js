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

export async function getArtifact(runId, name) {
  const resp = await fetch(`${BASE}/engagements/${runId}/artifacts/${name}`)
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
  return resp.text()
}

export async function planReview(runId, action) {
  return _json(await fetch(`${BASE}/engagements/${runId}/plan-review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action }),
  }))
}

export async function reportChat(runId, message) {
  return _json(await fetch(`${BASE}/engagements/${runId}/report-chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  }))
}
