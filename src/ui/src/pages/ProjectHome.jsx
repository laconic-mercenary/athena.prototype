import { useState, useEffect } from 'react'
import { listProjects, deleteProject } from '../api'
import { CreateProjectModal } from '../components/CreateProjectModal'
import { RenameProjectModal } from '../components/RenameProjectModal'
import { ConfirmModal } from '../components/ConfirmModal'

export function ProjectHome({ onSelectProject }) {
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [renaming, setRenaming] = useState(null)   // project name being renamed
  const [deleting, setDeleting] = useState(null)   // project name pending delete confirm
  const [deleteError, setDeleteError] = useState(null)

  function refresh() {
    setLoading(true)
    listProjects()
      .then(d => setProjects(d.projects))
      .catch(() => setProjects([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => { refresh() }, [])

  async function handleDelete() {
    try {
      await deleteProject(deleting)
      setDeleting(null)
      refresh()
    } catch (err) {
      setDeleteError(err.message)
    }
  }

  return (
    <div className="request-page">
      <div className="request-card">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 28 }}>
          <h1 className="request-title">Athena</h1>
          <button type="button" className="plan-review-btn plan-review-btn--approve" onClick={() => setCreating(true)}>
            + New project
          </button>
        </div>
        <p className="request-label">Projects</p>
        {loading && <div className="panel-empty">Loading…</div>}
        {!loading && projects.length === 0 && (
          <div className="panel-empty">No projects yet — create one to start an engagement.</div>
        )}
        {!loading && projects.length > 0 && (
          <div className="artifact-list">
            {projects.map(p => (
              <div key={p.name} className="project-row">
                <button type="button" className="project-row-name" onClick={() => onSelectProject(p.name)}>
                  {p.name}
                </button>
                <div className="project-row-actions">
                  <button type="button" className="icon-btn" title="Rename" onClick={() => setRenaming(p.name)}>✎</button>
                  <button type="button" className="icon-btn icon-btn--danger" title="Delete" onClick={() => { setDeleteError(null); setDeleting(p.name) }}>✕</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {creating && (
        <CreateProjectModal
          onClose={() => setCreating(false)}
          onCreated={() => { setCreating(false); refresh() }}
        />
      )}
      {renaming && (
        <RenameProjectModal
          currentName={renaming}
          onClose={() => setRenaming(null)}
          onRenamed={() => { setRenaming(null); refresh() }}
        />
      )}
      {deleting && (
        <ConfirmModal
          title="Delete project"
          body={deleteError || `Delete "${deleting}"? This cannot be undone. Projects with live engagements can't be deleted.`}
          confirmLabel="Delete"
          onConfirm={handleDelete}
          onCancel={() => { setDeleting(null); setDeleteError(null) }}
        />
      )}
    </div>
  )
}
