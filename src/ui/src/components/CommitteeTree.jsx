import { useState } from 'react'

export function Accordion({ label, defaultOpen = false, indent = 0, children, headerRight }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={{ marginBottom: 2 }}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: 5, width: '100%',
          background: 'none', border: 'none', cursor: 'pointer',
          padding: `3px 0 3px ${indent * 12}px`,
          color: '#64748b', fontSize: 10, fontWeight: 600, letterSpacing: 0.5,
          textTransform: 'uppercase', textAlign: 'left',
        }}
      >
        <span style={{ fontSize: 8, color: '#3b5270', flexShrink: 0, width: 8 }}>{open ? '▼' : '▸'}</span>
        <span style={{ flex: 1 }}>{label}</span>
        {headerRight}
      </button>
      {open && <div style={{ paddingLeft: (indent + 1) * 12 }}>{children}</div>}
    </div>
  )
}

export function SpecialistRow({ specialist, disabled, onToggle }) {
  const interactive = typeof onToggle === 'function'
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 8,
      padding: '4px 0', borderBottom: '1px solid #0d1a2a',
    }}>
      {interactive ? (
        <input
          type="checkbox"
          checked={!disabled}
          onChange={e => onToggle(e.target.checked)}
          style={{ marginTop: 2, accentColor: '#3b82f6', flexShrink: 0, cursor: 'pointer' }}
        />
      ) : (
        <span style={{
          marginTop: 3, width: 10, height: 10, flexShrink: 0,
          borderRadius: 2, border: `1px solid ${disabled ? '#1e3050' : '#3b5270'}`,
          background: disabled ? 'transparent' : '#1e3050',
          display: 'inline-block',
        }} />
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <span style={{
          fontSize: 11, fontWeight: 600,
          color: disabled ? '#334155' : '#94a3b8',
          textDecoration: disabled ? 'line-through' : 'none',
        }}>
          {specialist.title}
        </span>
        {specialist.skills?.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 3 }}>
            {specialist.skills.map(skill => (
              <span key={skill} style={{
                fontSize: 9, padding: '1px 5px', borderRadius: 3,
                background: '#071020', border: '1px solid #1e3050',
                color: disabled ? '#1e3050' : '#3b5270', letterSpacing: 0.3,
              }}>{skill}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// Single-committee tree: objectives accordion + elements accordion with specialists.
// onToggleSpecialist is optional — omit for read-only display.
export function CommitteePanel({ committee, objectives, disabledSpecialists, onToggleSpecialist }) {
  if (!committee) return null
  const name = committee.name
  const ds = disabledSpecialists || {}

  return (
    <div>
      {objectives?.length > 0 && (
        <Accordion label="Objectives" defaultOpen={true} indent={0}>
          {objectives.map((obj, j) => (
            <div key={j} style={{
              fontSize: 11, color: '#64748b', lineHeight: 1.6,
              marginBottom: 3, paddingLeft: 4, borderLeft: '2px solid #1e3050',
            }}>
              {obj}
            </div>
          ))}
        </Accordion>
      )}

      {committee.elements?.length > 0 && (
        <Accordion label={`Elements · ${committee.elements.length}`} defaultOpen={false} indent={0}>
          {committee.elements.map(el => {
            const allDisabled = el.specialists?.every(sp => ds[`${name}/${el.id}/${sp.id}`])
            return (
              <Accordion
                key={el.id}
                label={el.label || el.id}
                defaultOpen={false}
                indent={0}
                headerRight={allDisabled
                  ? <span style={{ fontSize: 8, color: '#ef4444', letterSpacing: 0.5 }}>disabled</span>
                  : null}
              >
                {(el.specialists || []).map(sp => {
                  const key = `${name}/${el.id}/${sp.id}`
                  return (
                    <SpecialistRow
                      key={sp.id}
                      specialist={sp}
                      disabled={!!ds[key]}
                      onToggle={onToggleSpecialist
                        ? enabled => onToggleSpecialist(key, enabled)
                        : undefined}
                    />
                  )
                })}
              </Accordion>
            )
          })}
        </Accordion>
      )}
    </div>
  )
}
