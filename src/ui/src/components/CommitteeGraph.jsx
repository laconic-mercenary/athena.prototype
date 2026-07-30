import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ReactFlow,
  Background,
  Handle,
  Position,
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

const ORCHESTRATOR_AGENT_ID = 'athena.orchestrator'

function formatTs(ts) {
  const d = new Date(ts)
  return (
    String(d.getHours()).padStart(2, '0') + ':' +
    String(d.getMinutes()).padStart(2, '0') + ':' +
    String(d.getSeconds()).padStart(2, '0') + '.' +
    String(d.getMilliseconds()).padStart(3, '0')
  )
}

// Palette assigned by committee index for dynamic ensembles.
const COMMITTEE_PALETTE = ['#f97316', '#22c55e', '#ef4444', '#eab308', '#3b82f6', '#a855f7', '#06b6d4']

function committeeColor(name, index) {
  const fixed = { orchestrator: '#e2e8f0' }
  return fixed[name] || COMMITTEE_PALETTE[index % COMMITTEE_PALETTE.length]
}

const FINDING_BORDER = { signal_critical: '#ef4444', signal_warn: '#f97316' }
const FINDING_LABEL  = { signal_critical: 'CRIT', signal_warn: 'WARN', signal_info: 'INFO' }
const GATE_COLORS    = { advance: '#22c55e', retry: '#ef4444', iterate: '#f97316' }

// ── Tool result modal ─────────────────────────────────────────────────────────
function ToolResultModal({ tool, inputSummary, result, ts, color, onClose, onDiscuss }) {
  let displayResult = result || '(pending…)'
  try { displayResult = JSON.stringify(JSON.parse(result), null, 2) } catch { /* raw */ }

  let displayInput = ''
  try { displayInput = JSON.stringify(JSON.parse(inputSummary), null, 2) } catch { displayInput = inputSummary || '' }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(0,0,0,0.65)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: '#0f172a', border: `1px solid ${color}44`,
          borderRadius: 8, padding: '20px 24px',
          maxWidth: 640, width: '90vw', maxHeight: '72vh',
          display: 'flex', flexDirection: 'column', gap: 12,
          boxShadow: `0 0 40px rgba(0,0,0,0.8)`,
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: `${color}cc`, fontFamily: 'monospace' }}>{tool}</span>
          <span style={{ fontSize: 9, color: '#475569', fontVariantNumeric: 'tabular-nums' }}>{formatTs(ts)}</span>
        </div>

        {displayInput && (
          <div>
            <div style={{ fontSize: 8, letterSpacing: 1.5, color: '#475569', marginBottom: 4 }}>INPUT</div>
            <pre style={{
              margin: 0, fontSize: 10, color: '#64748b', fontFamily: 'monospace',
              background: '#07101f', borderRadius: 4, padding: '8px 10px',
              overflow: 'auto', maxHeight: 100, whiteSpace: 'pre-wrap', wordBreak: 'break-all',
            }}>{displayInput}</pre>
          </div>
        )}

        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ fontSize: 8, letterSpacing: 1.5, color: '#475569' }}>RESULT</div>
          <pre style={{
            margin: 0, flex: 1, overflow: 'auto',
            fontSize: 10, color: '#94a3b8', fontFamily: 'monospace',
            background: '#07101f', borderRadius: 4, padding: '8px 10px',
            whiteSpace: 'pre-wrap', wordBreak: 'break-all',
          }}>{displayResult}</pre>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          {onDiscuss && (
            <button onClick={onDiscuss} style={{
              background: 'none', border: `1px solid ${color}55`, borderRadius: 4,
              color: `${color}aa`, fontSize: 10, padding: '4px 14px', cursor: 'pointer',
            }}>Discuss</button>
          )}
          <button onClick={onClose} style={{
            background: 'none', border: '1px solid #334155', borderRadius: 4,
            color: '#64748b', fontSize: 10, padding: '4px 14px', cursor: 'pointer',
          }}>Close</button>
        </div>
      </div>
    </div>
  )
}

// ── Result modal (compare-mode element selection) ─────────────────────────────
function ResultModal({ elementId, winnerId, winnerTitle, rationale, variants, color, onClose }) {
  const [activeIdx, setActiveIdx] = useState(0)
  const [canLeft, setCanLeft]   = useState(false)
  const [canRight, setCanRight] = useState(false)
  const tabBarRef = useRef(null)

  // Winner first, then losers in original order.
  const winnerVar = variants.find(v => v.label === winnerId) || variants[0]
  const loserVars = variants.filter(v => v.label !== winnerId)
  const ordered   = winnerVar ? [winnerVar, ...loserVars] : [...loserVars]

  const checkScroll = () => {
    const el = tabBarRef.current
    if (!el) return
    setCanLeft(el.scrollLeft > 1)
    setCanRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 1)
  }

  useEffect(() => {
    checkScroll()
    const el = tabBarRef.current
    if (!el) return
    el.addEventListener('scroll', checkScroll)
    const ro = new ResizeObserver(checkScroll)
    ro.observe(el)
    return () => { el.removeEventListener('scroll', checkScroll); ro.disconnect() }
  }, [variants])

  const nudge = (dir) => tabBarRef.current?.scrollBy({ left: dir * 130, behavior: 'smooth' })

  const active  = ordered[activeIdx] || ordered[0]
  const isWin   = active?.label === winnerId

  let displayOutput = active?.output || '(none)'
  try { displayOutput = JSON.stringify(JSON.parse(active?.output), null, 2) } catch { /* raw */ }

  const ARROW = {
    background: 'none', border: '1px solid #1e293b', borderRadius: 3,
    color: '#475569', fontSize: 13, width: 22, height: 22,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    cursor: 'pointer', flexShrink: 0, lineHeight: 1,
  }

  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.65)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClose}
    >
      <div
        style={{ background: '#0f172a', border: `1px solid ${color}44`, borderRadius: 8, padding: '20px 24px', maxWidth: 640, width: '90vw', maxHeight: '80vh', display: 'flex', flexDirection: 'column', gap: 12, boxShadow: '0 0 40px rgba(0,0,0,0.8)' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: `${color}cc`, fontFamily: 'monospace' }}>{elementId}</span>
          <span style={{ fontSize: 9, color: '#475569', letterSpacing: 1 }}>RESULT</span>
        </div>

        {/* Tab strip */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, borderBottom: `1px solid #1e293b`, paddingBottom: 8 }}>
          {canLeft && (
            <button style={ARROW} onClick={() => nudge(-1)}>‹</button>
          )}
          <div
            ref={tabBarRef}
            style={{ display: 'flex', gap: 2, overflow: 'hidden', flex: 1 }}
          >
            {ordered.map((v, i) => {
              const win      = v.label === winnerId
              const tabColor = win ? '#22c55e' : '#f97316'
              const isActive = i === activeIdx
              const label    = win ? `★ ${winnerTitle || v.title || v.label}` : (v.title || v.label)
              return (
                <button
                  key={v.label}
                  onClick={() => setActiveIdx(i)}
                  style={{
                    flexShrink: 0, whiteSpace: 'nowrap',
                    fontSize: 9, fontWeight: 700, letterSpacing: 0.5,
                    padding: '3px 12px', cursor: 'pointer', border: 'none',
                    borderRadius: '3px 3px 0 0',
                    background: isActive ? `${tabColor}18` : 'none',
                    color: isActive ? tabColor : `${tabColor}55`,
                    borderBottom: isActive ? `2px solid ${tabColor}` : '2px solid transparent',
                    transition: 'color 0.15s, border-color 0.15s',
                  }}
                >
                  {label}
                </button>
              )
            })}
          </div>
          {canRight && (
            <button style={ARROW} onClick={() => nudge(1)}>›</button>
          )}
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', gap: 8, minHeight: 0 }}>
          <pre style={{
            margin: 0, flex: 1, overflow: 'auto', minHeight: 0,
            fontSize: 10, color: '#94a3b8', fontFamily: 'monospace',
            background: '#07101f', borderRadius: 4, padding: '8px 10px',
            whiteSpace: 'pre-wrap', wordBreak: 'break-all',
          }}>{displayOutput}</pre>

          {isWin && rationale && (
            <div style={{ flexShrink: 0 }}>
              <div style={{ fontSize: 8, letterSpacing: 1.5, color: '#475569', marginBottom: 4 }}>WHY THIS WON</div>
              <div style={{ fontSize: 11, color: '#94a3b8', lineHeight: 1.7, background: '#07101f', borderRadius: 4, padding: '10px 12px' }}>
                {rationale}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', flexShrink: 0 }}>
          <button onClick={onClose} style={{ background: 'none', border: '1px solid #334155', borderRadius: 4, color: '#64748b', fontSize: 10, padding: '4px 14px', cursor: 'pointer' }}>Close</button>
        </div>
      </div>
    </div>
  )
}

// ── Specialist sub-card (inside ElementNode) ──────────────────────────────────
function SpecialistCard({ agent, color, onToolClick, isWinner, winnerRationale }) {
  const recentTools = (agent.toolHistory || []).slice(-3).reverse()
  const isActive = agent.status === 'active'
  const winnerColor = '#22c55e'
  const [badgeHover, setBadgeHover] = useState(false)

  return (
    <div style={{
      background: '#07101f',
      border: isWinner ? `1px solid ${winnerColor}88` : `1px solid ${color}22`,
      borderRadius: 4, padding: '6px 9px', position: 'relative',
      overflow: 'visible',
      boxShadow: isWinner ? `0 0 8px ${winnerColor}33` : 'none',
    }}>
      {isWinner && (
        <div
          className="nopan nodrag"
          onMouseEnter={() => setBadgeHover(true)}
          onMouseLeave={() => setBadgeHover(false)}
          style={{
            position: 'absolute', top: -1, right: 8, zIndex: 5,
            background: winnerColor, color: '#000',
            fontSize: 7, fontWeight: 800, letterSpacing: 1.5,
            padding: '1px 6px', borderRadius: '0 0 3px 3px',
            textTransform: 'uppercase', cursor: winnerRationale ? 'help' : 'default',
          }}
        >
          winner
          {badgeHover && winnerRationale && (
            <div style={{
              position: 'absolute', top: 'calc(100% + 5px)', right: 0, width: 210, zIndex: 60,
              background: '#0f172a', border: `1px solid ${winnerColor}44`,
              borderRadius: 6, padding: '9px 11px', boxShadow: '0 6px 22px rgba(0,0,0,0.7)',
              fontSize: 9, fontWeight: 400, color: '#94a3b8', lineHeight: 1.55,
              letterSpacing: 0, textTransform: 'none', textAlign: 'left', whiteSpace: 'normal',
            }}>
              <div style={{ fontSize: 7.5, fontWeight: 800, letterSpacing: 1.5, color: winnerColor, marginBottom: 4 }}>
                WHY THIS WON
              </div>
              {winnerRationale}
            </div>
          )}
        </div>
      )}
      <div style={{ fontWeight: 700, fontSize: 10, color: isWinner ? `${winnerColor}cc` : `${color}aa`, marginBottom: recentTools.length ? 4 : 0 }}>
        {agent.title}
      </div>

      {recentTools.map((t, i) => {
        const hasResult = t.result !== undefined
        return (
          <div
            key={i}
            className="nopan nodrag"
            onPointerDown={e => e.stopPropagation()}
            onClick={hasResult && onToolClick ? (e => { e.stopPropagation(); onToolClick(t) }) : undefined}
            title={hasResult ? 'Click to view result' : undefined}
            style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 9, color: i === 0 ? `${color}88` : `${color}33`, lineHeight: 1.5, cursor: hasResult ? 'pointer' : 'default' }}
          >
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, minWidth: 0 }}>
              › {t.tool}
            </span>
            <span style={{ flexShrink: 0, fontSize: 8, opacity: 0.6, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap', fontFamily: 'monospace' }}>
              {formatTs(t.ts)}
            </span>
          </div>
        )
      })}

      {isActive && (
        <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 2, borderRadius: '0 0 4px 4px', overflow: 'hidden', background: `${color}18` }}>
          <div style={{ width: '38%', height: '100%', background: `linear-gradient(90deg, transparent, ${color}, transparent)`, animation: 'slide-bar 1.4s linear infinite' }} />
        </div>
      )}
    </div>
  )
}

// ── Element node ──────────────────────────────────────────────────────────────
function ElementNode({ data }) {
  const { elementId, elementLabel, color, agents, elementResult, onToolClick, onResult } = data
  const [hovered, setHovered] = useState(false)

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: '#080e1a', border: `1px solid ${color}33`,
        borderRadius: 6, padding: '7px 9px', minWidth: 210,
        display: 'flex', flexDirection: 'column', gap: 5,
        userSelect: 'none',
      }}
    >
      <Handle type="target" position={Position.Top} style={{ visibility: 'hidden' }} />

      <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 8, fontWeight: 800, letterSpacing: 2, color: `${color}55`, textTransform: 'uppercase', paddingBottom: 4, borderBottom: `1px solid ${color}18` }}>
        <svg width="10" height="10" viewBox="0 0 24 24" fill={`${color}66`} style={{ flexShrink: 0 }}>
          <rect x="4" y="2" width="16" height="7" rx="1.5"/>
          <rect x="9" y="9" width="6" height="13" rx="1.5"/>
        </svg>
        {elementLabel || elementId}
      </div>

      {agents.map(agent => (
        <SpecialistCard
          key={agent.id}
          agent={agent}
          color={color}
          onToolClick={onToolClick}
          isWinner={!!elementResult && agent.variant_label === elementResult.winnerId}
          winnerRationale={elementResult?.rationale}
        />
      ))}

      {elementResult && (
        <div className="nopan nodrag" onPointerDown={e => e.stopPropagation()}
          onClick={e => { e.stopPropagation(); onResult() }}
          style={{ marginTop: 2, textAlign: 'center', cursor: 'pointer' }}
        >
          <span style={{
            fontSize: 8, fontWeight: 700, letterSpacing: 1.5,
            color: hovered ? `${color}cc` : `${color}77`,
            border: `1px solid ${hovered ? color + '88' : color + '44'}`,
            borderRadius: 3, padding: '2px 10px', display: 'inline-block',
            transition: 'color 0.15s, border-color 0.15s',
          }}>RESULT</span>
        </div>
      )}

      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  )
}

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

// ── Committee label node (visual-only header above leader) ───────────────────
function CommitteeLabelNode({ data }) {
  const { label, color, status, objective } = data
  const isActive = status === 'active'
  const isDone   = status === 'completed'
  const [hovered, setHovered] = useState(false)
  const hasObjective = Array.isArray(objective) && objective.length > 0

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
      background: '#07101f',
      border: `1px solid ${color}33`,
      borderRadius: 5,
      padding: '4px 14px',
      color: `${color}99`,
      fontWeight: 800,
      fontSize: 9,
      letterSpacing: 2,
      textTransform: 'uppercase',
      textAlign: 'center',
      minWidth: 90,
      opacity: isDone ? 0.55 : 1,
      userSelect: 'none',
      cursor: hasObjective ? 'help' : 'default',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 6,
      position: 'relative',
    }}>
      <Handle type="target" position={Position.Top}    style={{ visibility: 'hidden' }} />
      {label}
      {isActive && (
        <span style={{
          display: 'inline-block', width: 5, height: 5, borderRadius: '50%',
          background: color, boxShadow: `0 0 5px ${color}`,
          animation: 'node-pulse 1.8s ease-in-out infinite', flexShrink: 0,
        }} />
      )}
      {hovered && hasObjective && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 6px)', left: '50%', transform: 'translateX(-50%)',
          width: 240, zIndex: 60, textAlign: 'left',
          background: '#0f172a', border: `1px solid ${color}44`,
          borderRadius: 6, padding: '9px 11px', boxShadow: '0 6px 22px rgba(0,0,0,0.7)',
          fontWeight: 400, letterSpacing: 0, textTransform: 'none',
        }}>
          <div style={{ fontSize: 7.5, fontWeight: 800, letterSpacing: 1.5, color: `${color}cc`, marginBottom: 5 }}>
            OBJECTIVE
          </div>
          {objective.map((o, i) => (
            <div key={i} style={{ fontSize: 9, color: '#94a3b8', lineHeight: 1.55, marginBottom: 2 }}>
              • {o}
            </div>
          ))}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  )
}

// ── Committee node ────────────────────────────────────────────────────────────
function CommitteeNode({ data }) {
  const { label, color, status, classification, badgeCount, steps, onClick, onChat, onResults, pendingQuestion } = data
  const alertColor = FINDING_BORDER[classification]
  const isActive   = status === 'active'
  const isDone     = status === 'completed'
  const [hovered, setHovered] = useState(false)

  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
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

      {isDone && onResults && (
        <div className="nopan nodrag" onPointerDown={e => e.stopPropagation()}
          onClick={e => { e.stopPropagation(); onResults() }}
          style={{ marginTop: 9, textAlign: 'center', cursor: 'pointer' }}
        >
          <span style={{
            fontSize: 8, fontWeight: 700, letterSpacing: 1.5,
            color: `${color}99`,
            border: `1px solid ${color}88`, borderRadius: 3,
            padding: '2px 10px', display: 'inline-block',
          }}>RESULTS</span>
        </div>
      )}

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

      {pendingQuestion && onChat && (
        <div className="nopan nodrag" onPointerDown={e => e.stopPropagation()}
          onClick={e => { e.stopPropagation(); onChat() }}
          style={{
            position: 'absolute', top: -26, left: '50%', transform: 'translateX(-50%)',
            background: '#ef4444', color: '#fff',
            borderRadius: 3, padding: '2px 8px',
            fontSize: 8, fontWeight: 800, letterSpacing: 1.5,
            cursor: 'pointer', whiteSpace: 'nowrap',
            boxShadow: '0 0 8px #ef444488', zIndex: 10,
          }}
        >QUESTION</div>
      )}

      {hovered && onChat && !pendingQuestion && (
        <div className="nopan nodrag" onPointerDown={e => e.stopPropagation()}
          onClick={e => { e.stopPropagation(); onChat() }}
          style={{ marginTop: 10, display: 'flex', justifyContent: 'center', cursor: 'pointer' }}
        >
          <div style={{
            width: 30, height: 30, borderRadius: '50%',
            background: '#0a1628', border: '1px solid #3b82f6',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#3b82f6', boxShadow: '0 0 8px #3b82f622',
          }}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
          </div>
        </div>
      )}

      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  )
}

// ── Agent node ────────────────────────────────────────────────────────────────
function AgentNode({ data }) {
  const { title, color, status, classification, toolHistory, onChat, onFinding, onToolClick, pendingQuestion, onResults } = data
  const alertColor = FINDING_BORDER[classification]
  const isActive   = status === 'active'
  const hasAlert   = !!alertColor
  const [hovered, setHovered] = useState(false)
  const hideTimer  = useRef(null)

  const handleEnter = () => {
    if (hideTimer.current) clearTimeout(hideTimer.current)
    setHovered(true)
  }
  const handleLeave = () => {
    hideTimer.current = setTimeout(() => setHovered(false), 1000)
  }

  const recentTools = (toolHistory || []).slice(-3).reverse()

  return (
    <div
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
      style={{
        background: '#080e1a',
        border: `1px solid ${alertColor ? alertColor + '88' : color + '44'}`,
        borderRadius: 6, padding: '8px 12px', minWidth: 200,
        position: 'relative', overflow: 'visible',
        boxShadow: isActive ? `0 0 10px 2px ${color}2a` : 'none',
        transition: 'box-shadow 0.4s', userSelect: 'none',
      }}
    >
      {/* Hover action menu — slides out to the left */}
      <div
        className="nopan nodrag"
        onMouseEnter={handleEnter}
        onMouseLeave={handleLeave}
        style={{
          position: 'absolute',
          right: 'calc(100% + 10px)',
          top: '50%',
          transform: 'translateY(-50%)',
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
          pointerEvents: hovered ? 'auto' : 'none',
          zIndex: 20,
        }}
      >
        {onChat && status !== 'spun_down' && (
          <div
            onPointerDown={e => e.stopPropagation()}
            onClick={e => { e.stopPropagation(); onChat() }}
            title="Chat with this agent"
            style={{
              width: 30, height: 30, borderRadius: '50%',
              background: '#0a1628',
              border: '1px solid #3b82f6',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              cursor: 'pointer', color: '#3b82f6',
              opacity: hovered ? 1 : 0,
              transform: hovered ? 'translateX(0)' : 'translateX(8px)',
              transition: 'opacity 0.15s ease, transform 0.15s ease',
              boxShadow: '0 0 8px #3b82f622',
            }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
          </div>
        )}
      </div>
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

      {pendingQuestion && onChat && (
        <div className="nopan nodrag" onPointerDown={e => e.stopPropagation()}
          onClick={e => { e.stopPropagation(); onChat() }}
          style={{
            position: 'absolute', top: -22, left: '50%', transform: 'translateX(-50%)',
            background: '#ef4444', color: '#fff',
            borderRadius: 3, padding: '2px 6px',
            fontSize: 7, fontWeight: 800, letterSpacing: 1.5,
            cursor: 'pointer', whiteSpace: 'nowrap',
            boxShadow: '0 0 6px #ef444488', zIndex: 10,
          }}
        >QUESTION</div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontWeight: 700, fontSize: 11, color: `${color}cc`, marginBottom: recentTools.length ? 5 : 0 }}>
        <svg width="10" height="10" viewBox="0 0 24 22" fill={`${color}55`} style={{ flexShrink: 0 }}>
          <path d="M2,20 L22,20 L22,17 L20,9 L16,14 L12,5 L8,14 L4,9 L2,17 Z"/>
        </svg>
        {title}
      </div>

      {recentTools.map((t, i) => {
        const hasResult = t.result !== undefined
        return (
          <div
            key={i}
            className="nopan nodrag"
            onPointerDown={e => e.stopPropagation()}
            onClick={hasResult && onToolClick ? (e => { e.stopPropagation(); onToolClick(t) }) : undefined}
            title={hasResult ? 'Click to view result' : undefined}
            style={{
              display: 'flex', alignItems: 'center', gap: 4,
              fontSize: 9, color: i === 0 ? `${color}88` : `${color}33`,
              lineHeight: 1.5, cursor: hasResult ? 'pointer' : 'default',
            }}
          >
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, minWidth: 0 }}>
              › {t.tool}
            </span>
            <span style={{
              flexShrink: 0, fontSize: 8, opacity: 0.6,
              fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap',
              fontFamily: 'monospace',
            }}>
              {formatTs(t.ts)}
            </span>
          </div>
        )
      })}

      {onResults && (
        <div className="nopan nodrag" onPointerDown={e => e.stopPropagation()}
          onClick={e => { e.stopPropagation(); onResults() }}
          style={{ marginTop: 7, paddingTop: 5, borderTop: `1px solid ${color}1a`, textAlign: 'center', cursor: 'pointer' }}
        >
          <span style={{
            fontSize: 8, fontWeight: 700, letterSpacing: 1.5,
            color: `${color}99`, border: `1px solid ${color}88`, borderRadius: 3,
            padding: '2px 10px', display: 'inline-block',
          }}>RESULTS</span>
        </div>
      )}

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

// ── Gate back-edge (retry / iterate) with a hover tooltip ─────────────────────
function GateEdgeLabel({ data }) {
  const [hovered, setHovered] = useState(false)
  const color = GATE_COLORS[data.decision] || '#94a3b8'
  const crossCommittee = data.to && data.committee && data.to !== data.committee
  return (
    <div
      className="nodrag nopan"
      style={{ position: 'relative', pointerEvents: 'all' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {data.subtle ? (
        // Forward advance edges are always drawn — a subtle dot keeps them quiet
        // until hovered, unlike the loud chip used for occasional back-edges.
        <div style={{
          width: 10, height: 10, borderRadius: '50%',
          background: '#07101f', border: `1px solid ${color}${hovered ? 'cc' : '55'}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          cursor: 'help', transition: 'border-color 0.15s',
        }}>
          <div style={{ width: 3, height: 3, borderRadius: '50%', background: hovered ? color : `${color}77` }} />
        </div>
      ) : (
        <div style={{
          fontSize: 8, fontWeight: 700, letterSpacing: 0.5,
          color, background: '#07101f', border: `1px solid ${color}66`,
          borderRadius: 3, padding: '2px 7px', whiteSpace: 'nowrap', cursor: 'help',
        }}>
          {data.label}
        </div>
      )}
      {hovered && (
        <div style={{
          position: 'absolute', bottom: 'calc(100% + 6px)', left: '50%',
          transform: 'translateX(-50%)', zIndex: 60,
          width: 230, background: '#0f172a', border: `1px solid ${color}44`,
          borderRadius: 6, padding: '9px 11px', boxShadow: '0 6px 22px rgba(0,0,0,0.7)',
          fontSize: 9, color: '#94a3b8', lineHeight: 1.55, whiteSpace: 'normal', textAlign: 'left',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 5 }}>
            <span style={{ fontWeight: 800, color, letterSpacing: 1, textTransform: 'uppercase' }}>
              {data.decision}{crossCommittee ? ` → ${data.to}` : ''}
            </span>
            {data.decidedBy && (
              <span style={{ fontSize: 7.5, letterSpacing: 1, textTransform: 'uppercase', color: '#475569' }}>
                {data.decidedBy}
              </span>
            )}
          </div>
          {data.attempt && (
            <div style={{ fontSize: 8, color: '#64748b', marginBottom: 5 }}>Attempt {data.attempt}</div>
          )}
          {data.rationale
            ? <div>{data.rationale}</div>
            : <div style={{ color: '#475569', fontStyle: 'italic' }}>No rationale provided.</div>}
          {data.nextObjective && (
            <div style={{ marginTop: 6, paddingTop: 6, borderTop: `1px solid ${color}22` }}>
              <div style={{ fontSize: 7.5, fontWeight: 800, letterSpacing: 1.5, color: `${color}aa`, marginBottom: 3 }}>
                REFINED NEXT OBJECTIVE
              </div>
              <div>{data.nextObjective}</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Faint chevrons that travel along an edge toward its target and fade out — a
// directional "current" indicator. Each chevron follows the edge's own path via
// <mpath>, staggered in time so a small train of arrows flows continuously.
function EdgeChevrons({ edgeId, color, count = 3, dur = 1.9 }) {
  return Array.from({ length: count }).map((_, i) => {
    const begin = `${(i * dur) / count}s`
    return (
      <path
        key={i}
        d="M -3 -3 L 3 0 L -3 3"
        fill="none"
        stroke={color}
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0"
        style={{ pointerEvents: 'none' }}
      >
        <animateMotion dur={`${dur}s`} begin={begin} repeatCount="indefinite" rotate="auto">
          <mpath href={`#${edgeId}`} />
        </animateMotion>
        <animate
          attributeName="opacity"
          dur={`${dur}s`}
          begin={begin}
          repeatCount="indefinite"
          values="0;0.8;0"
          keyTimes="0;0.45;1"
        />
      </path>
    )
  })
}

function GateEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, data }) {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition,
  })
  const color = GATE_COLORS[data?.decision] || '#94a3b8'
  return (
    <>
      <BaseEdge id={id} path={edgePath} style={style} />
      {data?.flow && <EdgeChevrons edgeId={id} color={color} />}
      <EdgeLabelRenderer>
        <div style={{
          position: 'absolute',
          transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
          pointerEvents: 'all',
        }}>
          <GateEdgeLabel data={data} />
        </div>
      </EdgeLabelRenderer>
    </>
  )
}

// Structural / active edges — no label, just the flowing chevrons when active.
function FlowEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, data }) {
  const [edgePath] = getSmoothStepPath({
    sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition,
  })
  return (
    <>
      <BaseEdge id={id} path={edgePath} style={style} />
      {data?.flow && <EdgeChevrons edgeId={id} color={data.flowColor || '#3b82f6'} />}
    </>
  )
}

const nodeTypes = { committee: CommitteeNode, committeeLabel: CommitteeLabelNode, agent: AgentNode, element: ElementNode, finding: FindingNode }
const edgeTypes = { gate: GateEdge, flow: FlowEdge }

const ORCH_POS  = { x: 0, y: 0 }
const COMM_Y    = 115            // committee-label row (below orchestrator)
const COMM_GAP  = 280            // horizontal gap between committee columns
const COMM_LABEL_HEIGHT = 62     // committee label → first leader
const NODE_V_GAP = 36            // vertical gap between stacked leader/element nodes
const FINDING_GAP    = 88
const FINDING_INIT_Y = 0

// Static per-type node z-index. Applied to EVERY node (no undefined values, no
// hover-driven changes) so React Flow keeps a stable render layering. Committee
// labels sit above the leaders/elements below them so their downward tooltips
// (objective) clear those nodes without any dynamic elevation.
const Z_COMMITTEE = 20
const Z_LEADER    = 10
const Z_ELEMENT   = 10
const Z_ORCH      = 10
const Z_FINDING   = 5

// Node heights are content-driven, so we stack each column with a running cursor
// rather than fixed offsets. These estimators approximate the rendered card height
// (padding + rows + buttons); NODE_V_GAP absorbs the small error so nothing collides.
function estimateLeaderHeight(agent, hasResults) {
  const nTools = Math.min(3, (agent.toolHistory || []).length)
  return 30 + nTools * 14 + (hasResults ? 30 : 0)
}
function estimateElementHeight(specialistCount, hasResult) {
  return 42 + specialistCount * 46 + (hasResult ? 22 : 0)
}

// Horizontal alignment of a column's (wide) leader/element cards relative to its
// (narrow) committee-label node. Cards fan outward from the centre: the leftmost
// column right-aligns to its label, the rightmost left-aligns, middles centre.
const LABEL_W = 92    // approx committee-label node width
const CARD_W  = 214   // approx leader/element card width
function columnXOffset(index, count) {
  if (count === 1)         return (LABEL_W - CARD_W) / 2   // sole column: centred
  if (index === 0)         return LABEL_W - CARD_W          // leftmost: right edges align
  if (index === count - 1) return 0                         // rightmost: left edges align
  return (LABEL_W - CARD_W) / 2                             // middle: centred
}

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

export function CommitteeGraph({ state, dispatch, onCommitteeResults }) {
  const { committees, agents, steps, engagement, gateDecisions, plan, pendingLeaderQuestions, pendingOrchestratorQuestion } = state
  const [selectedResult, setSelectedResult] = useState(null)

  const committeeNames = useMemo(() => Object.keys(committees), [committees])
  const positions      = useMemo(() => computeCommitteePositions(committeeNames), [committeeNames])
  const [selectedTool, setSelectedTool] = useState(null)

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
      zIndex: Z_ORCH,
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
        pendingQuestion: pendingOrchestratorQuestion,
        onChat: () => dispatch({
          type: 'OPEN_CHAT',
          payload: {
            agentId: ORCHESTRATOR_AGENT_ID,
            committeeId: null,
            agentTitle: 'Orchestrator',
            findings: [],
          },
        }),
      },
    }
  }, [positions, engagement.status, pendingOrchestratorQuestion, dispatch])

  // ── Committee nodes ───────────────────────────────────────────────────────
  const committeeNodes = useMemo(() =>
    committeeNames.map((name, i) => {
      const pos   = positions[name] || { x: i * COMM_GAP, y: COMM_Y }
      const data  = committees[name] || {}
      const color = committeeColor(name, i)
      const nodeId = `committee-${name}`
      return {
        id: nodeId,
        type: 'committeeLabel',
        position: pos,
        zIndex: Z_COMMITTEE,
        data: {
          label: name, color, status: data.status || 'inactive',
          objective: plan?.committees?.[name]?.objective,
        },
      }
    }),
    [committeeNames, committees, positions, plan]
  )

  // ── Agent nodes (leaders only) + Element nodes (specialist groups) ────────
  const { leaderNodes, elementNodes: elementAgentNodes } = useMemo(() => {
    const byCommittee = {}
    Object.values(agents).forEach(a => {
      if (!byCommittee[a.committee]) byCommittee[a.committee] = []
      byCommittee[a.committee].push(a)
    })

    const leaders = []
    const elements = []

    Object.entries(byCommittee).forEach(([committee, list]) => {
      const committeeIndex = committeeNames.indexOf(committee)
      const parentPos = positions[committee] || { x: committeeIndex * COMM_GAP, y: COMM_Y }
      const colX = parentPos.x + columnXOffset(committeeIndex, committeeNames.length)
      const color = committeeColor(committee, committeeIndex)
      const leaderId = Object.keys(agents).find(
        id => agents[id].committee === committee && agents[id].role === 'leader'
      )
      const chatAgentId    = leaderId || ''
      const chatAgentTitle = (leaderId && agents[leaderId]?.title) || `${committee} lead`
      const chatFindings   = (leaderId && agents[leaderId]?.findings) || []

      const leaderList   = list.filter(a => a.role === 'leader')
      const specialistList = list.filter(a => a.role !== 'leader')

      // Running vertical cursor for this column — each node advances it by its own
      // estimated height so leaders and elements never overlap regardless of content.
      let cursorY = parentPos.y + COMM_LABEL_HEIGHT

      // Leader nodes — positioned where CommitteeNode was; carry RESULTS capability
      const isCompleted = (committees[committee] || {}).status === 'completed'
      leaderList.forEach((agent) => {
        const leaderY = cursorY
        const hasResults = isCompleted && !!onCommitteeResults
        cursorY += estimateLeaderHeight(agent, hasResults) + NODE_V_GAP
        leaders.push({
          id: `agent-${agent.id}`,
          type: 'agent',
          position: { x: colX, y: leaderY },
          zIndex: Z_LEADER,
          data: {
            title: agent.title || agent.id.split('.').pop(),
            color,
            status: agent.status,
            classification: agent.classification || null,
            toolHistory: agent.toolHistory || [],
            pendingQuestion: pendingLeaderQuestions[committee]?.question || null,
            onResults: (isCompleted && onCommitteeResults) ? () => onCommitteeResults(committee) : undefined,
            onChat: () => dispatch({ type: 'OPEN_CHAT', payload: { agentId: agent.id, committeeId: committee, agentTitle: agent.title || agent.id, findings: agent.findings || [] } }),
            onFinding: () => dispatch({ type: 'OPEN_CHAT', payload: { agentId: agent.id, committeeId: committee, agentTitle: agent.title || agent.id, findings: agent.findings || [], focusFindings: true } }),
            onToolClick: (entry) => setSelectedTool({ ...entry, color, chatAgentId: agent.id, committeeId: committee, chatAgentTitle: agent.title || agent.id, chatFindings: agent.findings || [] }),
          },
        })
      })

      // Group specialists by element_id
      const byElement = {}
      specialistList.forEach(a => {
        const eid = a.element_id || a.id
        if (!byElement[eid]) byElement[eid] = []
        byElement[eid].push(a)
      })

      const elementEntries = Object.entries(byElement)
      elementEntries.forEach(([eid, elementAgents]) => {
        const elementResult = committees[committee]?.elementResults?.[eid] || null
        const nodeId = `element-${committee}-${eid}`
        const elementLabel = elementAgents[0]?.element_label || eid
        const elementY = cursorY
        cursorY += estimateElementHeight(elementAgents.length, !!elementResult) + NODE_V_GAP
        elements.push({
          id: nodeId,
          type: 'element',
          position: {
            x: colX,
            y: elementY,
          },
          zIndex: Z_ELEMENT,
          data: {
            elementId: eid,
            elementLabel,
            color,
            agents: elementAgents,
            elementResult,
            onToolClick: (entry) => setSelectedTool({ ...entry, color, chatAgentId, committeeId: committee, chatAgentTitle, chatFindings }),
            onResult: () => setSelectedResult({ ...elementResult, elementId: elementLabel, color, variants: elementResult?.variants || [] }),
          },
        })
      })
    })

    return { leaderNodes: leaders, elementNodes: elements }
  }, [agents, committeeNames, positions, committees, pendingLeaderQuestions, onCommitteeResults, dispatch])

  // ── Edges ─────────────────────────────────────────────────────────────────
  const edges = useMemo(() => {
    const result = []

    // Build leader-id lookup so committee-level edges can target leader agents directly
    const leaderIdByCommittee = {}
    Object.values(agents).forEach(a => {
      if (a.role === 'leader') leaderIdByCommittee[a.committee] = a.id
    })

    // Orchestrator → committee label node
    committeeNames.forEach((name, i) => {
      const color = committeeColor(name, i)
      const active = committees[name]?.status === 'active'
      result.push({
        id: `e-orch-${name}`,
        source: 'committee-orchestrator',
        target: `committee-${name}`,
        type: 'flow',
        style: { stroke: active ? `${color}66` : '#1a2540' },
        data: { flow: active, flowColor: color },
      })
    })

    // Committee label → leader agent
    committeeNames.forEach((name, i) => {
      const leaderId = leaderIdByCommittee[name]
      if (!leaderId) return
      const color = committeeColor(name, i)
      const active = committees[name]?.status === 'active'
      result.push({
        id: `e-comm-leader-${name}`,
        source: `committee-${name}`,
        target: `agent-${leaderId}`,
        type: 'flow',
        style: { stroke: active ? `${color}55` : '#1a2540' },
        data: { flow: active, flowColor: color },
      })
    })

    // Forward leader → next leader (in plan order)
    committeeNames.forEach((name, i) => {
      if (i < committeeNames.length - 1) {
        const nextName   = committeeNames[i + 1]
        const leaderId   = leaderIdByCommittee[name]
        const nextLeaderId = leaderIdByCommittee[nextName]
        if (!leaderId || !nextLeaderId) return
        const color = committeeColor(nextName, i + 1)
        const advanceDecision = gateDecisions.find(
          g => g.committee === name && g.decision === 'advance' && (!g.to || g.to === nextName)
        )
        const advancing = !!advanceDecision
        const fwd = {
          id: `e-fwd-${name}-${nextName}`,
          source: `agent-${leaderId}`,
          target: `agent-${nextLeaderId}`,
          style: { stroke: advancing ? `${color}88` : '#1a2540' },
        }
        if (advanceDecision) {
          // Hoverable advance edge — subtle dot, reveals the advance rationale; flows.
          fwd.type = 'gate'
          fwd.data = {
            subtle: true,
            flow: true,
            label: '→ advance',
            decision: 'advance',
            rationale: advanceDecision.rationale,
            nextObjective: advanceDecision.next_objective,
            to: advanceDecision.to,
            committee: name,
            decidedBy: advanceDecision.decidedBy,
            attempt: advanceDecision.attempt,
          }
        } else {
          fwd.type = 'flow'
          fwd.data = { flow: false, flowColor: color }
        }
        result.push(fwd)
      }
    })

    // Back-edges from gate decisions (retry / iterate)
    gateDecisions.forEach((g, idx) => {
      if ((g.decision === 'retry' || g.decision === 'iterate') && g.to) {
        const sourceId = leaderIdByCommittee[g.committee]
        const targetId = leaderIdByCommittee[g.to]
        if (!sourceId || !targetId) return
        const edgeColor = GATE_COLORS[g.decision]
        result.push({
          id: `e-back-${idx}`,
          source: `agent-${sourceId}`,
          target: `agent-${targetId}`,
          type: 'gate',
          style: {
            stroke: `${edgeColor}88`,
            strokeDasharray: '5 4',
            strokeWidth: 1.5,
          },
          data: {
            flow: true,
            label: g.decision === 'retry' ? '↩ retry' : '↻ iterate',
            decision: g.decision,
            rationale: g.rationale,
            to: g.to,
            committee: g.committee,
            decidedBy: g.decidedBy,
            attempt: g.attempt,
          },
        })
      }
    })

    // Leader → element nodes
    const seenElements = new Set()
    Object.values(agents).forEach(agent => {
      if (agent.role === 'leader') return
      const eid = agent.element_id || agent.id
      const nodeId = `element-${agent.committee}-${eid}`
      if (seenElements.has(nodeId)) return
      seenElements.add(nodeId)
      const leaderId = leaderIdByCommittee[agent.committee]
      if (!leaderId) return  // element floats until leader spawns (transient)
      const committeeIndex = committeeNames.indexOf(agent.committee)
      const color = committeeColor(agent.committee, committeeIndex)
      const active = agent.status === 'active'
      result.push({
        id: `e-elem-${nodeId}`,
        source: `agent-${leaderId}`,
        target: nodeId,
        type: 'flow',
        style: { stroke: active ? `${color}44` : `${color}18` },
        data: { flow: active, flowColor: color },
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
        zIndex: Z_FINDING,
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
      const sourceAgent = agents[f.agentId]
      const sourceNodeId = sourceAgent?.role === 'leader'
        ? `agent-${f.agentId}`
        : `element-${f.committee}-${sourceAgent?.element_id || f.agentId}`
      edges.push({
        id: `e-disc-${f.nodeId}`,
        source: sourceNodeId,
        target: f.nodeId,
        type: 'flow',
        style: { stroke: `${color}55`, strokeDasharray: '5 4', strokeWidth: 1 },
        data: { flow: f.agentStatus === 'active', flowColor: color },
      })
    })

    return { findingNodes: nodes, findingEdges: edges }
  }, [agents, committeeNames, findingX, dispatch])

  const allNodes = useMemo(
    () => [orchestratorNode, ...committeeNodes, ...leaderNodes, ...elementAgentNodes, ...findingNodes],
    [orchestratorNode, committeeNodes, leaderNodes, elementAgentNodes, findingNodes]
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
      {selectedResult && (
        <ResultModal
          elementId={selectedResult.elementId}
          winnerId={selectedResult.winnerId}
          winnerTitle={selectedResult.winnerTitle}
          rationale={selectedResult.rationale}
          result={selectedResult.result}
          variants={selectedResult.variants || []}
          color={selectedResult.color}
          onClose={() => setSelectedResult(null)}
        />
      )}
      {selectedTool && (
        <ToolResultModal
          tool={selectedTool.tool}
          inputSummary={selectedTool.input_summary}
          result={selectedTool.result}
          ts={selectedTool.ts}
          color={selectedTool.color}
          onClose={() => setSelectedTool(null)}
          onDiscuss={() => {
            setSelectedTool(null)
            dispatch({
              type: 'OPEN_CHAT',
              payload: {
                agentId: selectedTool.chatAgentId,
                committeeId: selectedTool.committeeId,
                agentTitle: selectedTool.chatAgentTitle,
                findings: selectedTool.chatFindings,
              },
            })
          }}
        />
      )}
      <style>{`
        @keyframes node-pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.35; }
        }
        @keyframes slide-bar {
          0%   { transform: translateX(-100%); }
          100% { transform: translateX(360%); }
        }
        .react-flow__node { overflow: visible !important; }
      `}</style>
      <ReactFlow
        nodes={allNodes}
        edges={allEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
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
