import { useState, useEffect } from 'react'
import { listProjectEngagements } from '../api'

export function EngagementList({ projectName, statusFilter, onSelect, selectedRunId }) {
  const [engagements, setEngagements] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!projectName) { setEngagements([]); return }
    setLoading(true)
    listProjectEngagements(projectName)
      .then(d => setEngagements(d.engagements))
      .catch(() => setEngagements([]))
      .finally(() => setLoading(false))
  }, [projectName])

  const filtered = statusFilter
    ? engagements.filter(e => e.status === statusFilter)
    : engagements

  if (loading) return <div className="panel-empty">Loading…</div>
  if (filtered.length === 0) return <div className="panel-empty">No engagements</div>

  return (
    <div className="artifact-list">
      {filtered.map(e => (
        <button
          key={e.run_id}
          type="button"
          className={`artifact-row${e.run_id === selectedRunId ? ' artifact-row--active' : ''}`}
          onClick={() => onSelect && onSelect(e)}
        >
          <span className="artifact-name">{e.run_id}</span>
          <span className="artifact-size">{e.status}</span>
        </button>
      ))}
    </div>
  )
}
