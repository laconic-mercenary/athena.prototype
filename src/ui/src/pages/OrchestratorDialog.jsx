import { useState, useRef, useEffect } from 'react'
import { marked } from 'marked'
import { sendChat } from '../api'

marked.setOptions({ breaks: true })

const TECHNIQUES = [
  { id: 'T1595', name: 'Active Scanning',                       impl: 'nmap_scan · check_port',              enabled: true,  tactic: 'Reconnaissance' },
  { id: 'T1590', name: 'Gather Victim Network Information',      impl: 'http_get · http_head · extract_links', enabled: true,  tactic: 'Reconnaissance' },
  { id: 'T1591', name: 'Gather Victim Org Information',          impl: 'theHarvester · recon-ng',             enabled: false, tactic: 'Reconnaissance' },
  { id: 'T1596', name: 'Search Open Technical Databases',        impl: 'shodan · censys · fofa',              enabled: false, tactic: 'Reconnaissance' },
  { id: 'T1598', name: 'Phishing for Information',               impl: 'gophish · evilginx',                  enabled: false, tactic: 'Reconnaissance' },
  { id: 'T1046', name: 'Network Service Discovery',              impl: 'ssh_banner · tcp_banner · tls_probe', enabled: true,  tactic: 'Discovery' },
  { id: 'T1016', name: 'System Network Configuration Discovery', impl: 'ifconfig · ip route · arp',           enabled: false, tactic: 'Discovery' },
  { id: 'T1018', name: 'Remote System Discovery',                impl: 'ping sweep · arp scan',               enabled: false, tactic: 'Discovery' },
  { id: 'T1083', name: 'File and Directory Discovery',           impl: 'gobuster · ffuf · dirb',              enabled: false, tactic: 'Discovery' },
  { id: 'T1087', name: 'Account Discovery',                      impl: 'enum4linux · ldapsearch',             enabled: false, tactic: 'Discovery' },
  { id: 'T1135', name: 'Network Share Discovery',                impl: 'smbclient · crackmapexec',            enabled: false, tactic: 'Discovery' },
  { id: 'T1110', name: 'Brute Force',                            impl: 'hydra · medusa · crowbar',            enabled: false, tactic: 'Credential Access' },
  { id: 'T1040', name: 'Network Sniffing',                       impl: 'tcpdump · wireshark · responder',     enabled: false, tactic: 'Credential Access' },
  { id: 'T1555', name: 'Credentials from Password Stores',       impl: 'mimikatz · LaZagne',                  enabled: false, tactic: 'Credential Access' },
  { id: 'T1212', name: 'Exploitation for Credential Access',     impl: 'custom exploits · CVE modules',       enabled: false, tactic: 'Credential Access' },
  { id: 'T1005', name: 'Data from Local System',                 impl: 'find · grep · tar',                   enabled: false, tactic: 'Collection' },
  { id: 'T1213', name: 'Data from Information Repositories',     impl: 'postgres_query · mysql_query',        enabled: false, tactic: 'Collection' },
  { id: 'T1059', name: 'Command and Scripting Interpreter',      impl: 'bash · python3 · powershell',         enabled: false, tactic: 'Execution' },
  { id: 'T1021', name: 'Remote Services',                        impl: 'ssh · rdp · winrm',                   enabled: false, tactic: 'Lateral Movement' },
  { id: 'T1041', name: 'Exfiltration Over C2 Channel',           impl: 'custom C2 · DNS tunneling',           enabled: false, tactic: 'Exfiltration' },
  { id: 'T1485', name: 'Data Destruction',                       impl: 'shred · wipe · rm -rf',               enabled: false, tactic: 'Impact' },
  { id: 'T1498', name: 'Network Denial of Service',              impl: 'hping3 · slowloris',                  enabled: false, tactic: 'Impact' },
]

const TOOLS = [
  { name: 'nmap',          desc: 'Port & host discovery',           impl: 'nmap_scan · check_port',              technique: 'T1595' },
  { name: 'curl',          desc: 'HTTP surface enumeration',         impl: 'http_get · http_head · extract_links', technique: 'T1590' },
  { name: 'service-probe', desc: 'Protocol & banner fingerprinting', impl: 'ssh_banner · tcp_banner · tls_probe', technique: 'T1046' },
  { name: 'nikto',         desc: 'Web vulnerability scanning',       impl: 'nikto -h target',                     technique: null },
  { name: 'gobuster',      desc: 'Directory & file brute-force',     impl: 'gobuster dir · ffuf',                 technique: null },
  { name: 'theHarvester',  desc: 'OSINT & email harvesting',         impl: 'theHarvester -d target',              technique: null },
  { name: 'shodan',        desc: 'Internet exposure search',         impl: 'shodan · censys · fofa',              technique: null },
  { name: 'hydra',         desc: 'Credential brute-force',           impl: 'hydra · medusa',                      technique: null },
  { name: 'sqlmap',        desc: 'SQL injection detection',          impl: 'sqlmap -u target',                    technique: null },
  { name: 'tcpdump',       desc: 'Network traffic capture',          impl: 'tcpdump · responder',                 technique: null },
  { name: 'impacket',      desc: 'SMB / Kerberos attacks',           impl: 'secretsdump · psexec · getTGT',       technique: null },
  { name: 'mimikatz',      desc: 'Windows credential extraction',    impl: 'sekurlsa · lsadump',                  technique: null },
  { name: 'metasploit',    desc: 'Exploitation framework',           impl: 'msfconsole · msfvenom',               technique: null },
]

const TACTIC_ORDER = [
  'Reconnaissance', 'Discovery', 'Credential Access',
  'Collection', 'Execution', 'Lateral Movement', 'Exfiltration', 'Impact',
]

function groupByTactic(techniques) {
  const groups = {}
  for (const t of techniques) {
    if (!groups[t.tactic]) groups[t.tactic] = []
    groups[t.tactic].push(t)
  }
  return groups
}

// MITRE ATT&CK tactics in canonical order.
// enabled = our pipeline has agents that cover this objective.
// tactic = the matching tactic name in TECHNIQUES (for counting selected techniques).
const OBJECTIVES = [
  {
    id: 'TA0043', name: 'Reconnaissance',      enabled: true,
    tactic: 'Reconnaissance',
    desc: 'Map the external attack surface — hosts, open ports, exposed services, and web endpoints.',
  },
  {
    id: 'TA0042', name: 'Resource Development', enabled: false,
    tactic: null,
    desc: 'Acquire infrastructure, accounts, and tooling required before active operations begin.',
  },
  {
    id: 'TA0001', name: 'Initial Access',       enabled: false,
    tactic: null,
    desc: 'Establish a foothold via phishing, exploitation of public-facing applications, or supply-chain compromise.',
  },
  {
    id: 'TA0002', name: 'Execution',            enabled: false,
    tactic: 'Execution',
    desc: 'Run adversary-controlled code on target systems to trigger further stages.',
  },
  {
    id: 'TA0003', name: 'Persistence',          enabled: false,
    tactic: null,
    desc: 'Maintain access across reboots, credential rotations, and defensive clean-up actions.',
  },
  {
    id: 'TA0004', name: 'Privilege Escalation', enabled: false,
    tactic: null,
    desc: 'Gain elevated permissions to unlock restricted resources and high-value targets.',
  },
  {
    id: 'TA0005', name: 'Defense Evasion',      enabled: false,
    tactic: null,
    desc: 'Bypass or suppress security controls, logging pipelines, and detection mechanisms.',
  },
  {
    id: 'TA0006', name: 'Credential Access',    enabled: false,
    tactic: 'Credential Access',
    desc: 'Harvest or brute-force credentials to authenticate as legitimate users.',
  },
  {
    id: 'TA0007', name: 'Discovery',            enabled: true,
    tactic: 'Discovery',
    desc: 'Enumerate internal network topology, live hosts, running services, and account structure.',
  },
  {
    id: 'TA0008', name: 'Lateral Movement',     enabled: false,
    tactic: 'Lateral Movement',
    desc: 'Pivot across the network to reach additional hosts, segments, and high-value systems.',
  },
  {
    id: 'TA0009', name: 'Collection',           enabled: true,
    tactic: 'Collection',
    desc: 'Retrieve and consolidate data from identified sources — databases, repositories, and local stores.',
  },
  {
    id: 'TA0011', name: 'Command and Control',  enabled: false,
    tactic: null,
    desc: 'Establish persistent, covert channels to direct ongoing agent operations from outside.',
  },
  {
    id: 'TA0010', name: 'Exfiltration',         enabled: false,
    tactic: 'Exfiltration',
    desc: 'Transfer collected data out of the target environment via covert or encrypted channels.',
  },
  {
    id: 'TA0040', name: 'Impact',               enabled: false,
    tactic: 'Impact',
    desc: 'Manipulate, disrupt, or destroy target systems, data, and availability.',
  },
]

export function OrchestratorDialog({ state, dispatch }) {
  const { engagement, dialogMessages } = state

  const [tab, setTab] = useState('objectives')
  const [panelOpen, setPanelOpen] = useState(false)
  const [selected, setSelected] = useState(() =>
    new Set(TECHNIQUES.filter(t => t.enabled).map(t => t.id))
  )
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)
  const [confirmed, setConfirmed] = useState(false)
  const messagesRef = useRef(null)

  useEffect(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight
    }
  }, [dialogMessages])

  function toggleTechnique(id) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function postMessage(text, isConfirm = false) {
    setSending(true)
    setError(null)
    try {
      dispatch({ type: 'DIALOG_OPERATOR_MESSAGE', payload: { text, isConfirm } })
      await sendChat(engagement.run_id, 'athena.orchestrator', text)
      setInput('')
    } catch (err) {
      setError(err.message)
      if (isConfirm) setConfirmed(false)
    } finally {
      setSending(false)
    }
  }

  function handleSend(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || sending || confirmed) return
    postMessage(text)
  }

  function handleConfirm() {
    if (confirmed || sending) return
    setConfirmed(true)
    postMessage('CONFIRM', true)
  }

  const tacticGroups = groupByTactic(TECHNIQUES)
  const lockedCount = TECHNIQUES.filter(t => !t.enabled).length
  const hasOrchMessage = dialogMessages.some(m => m.role === 'orch')

  return (
    <div className="dialog-shell">
      <div className="dialog-topbar">
        <span className="dialog-logo">Athena</span>
        <div className="dialog-steps">
          <span className="dialog-step dialog-step--done">Instructions</span>
          <span className="dialog-step-arrow">›</span>
          <span className="dialog-step dialog-step--active">Briefing</span>
          <span className="dialog-step-arrow">›</span>
          <span className="dialog-step dialog-step--next">Engagement</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            className={`dash-action-btn${panelOpen ? ' dash-action-btn--on' : ''}`}
            onClick={() => setPanelOpen(o => !o)}
          >
            {panelOpen ? 'Hide Techniques' : 'View Techniques'}
          </button>
          <span className="dialog-run-id">{engagement.run_id}</span>
        </div>
      </div>

      <div className="dialog-body">
        {/* ── Chat pane ── */}
        <div className="dialog-chat-pane">
          <div className="dialog-pane-header">
            <span className="dialog-agent-dot" />
            <span className="dialog-pane-label">Orchestrator</span>
          </div>

          <div className="dialog-messages" ref={messagesRef}>
            {dialogMessages.length === 0 && (
              <div className="dialog-waiting">Waiting for orchestrator…</div>
            )}
            {dialogMessages.map((msg, i) => (
              <div key={i} className={`dialog-msg dialog-msg--${msg.role}`}>
                <div className="dialog-msg-meta">
                  <span className={`dialog-msg-role dialog-msg-role--${msg.role}`}>
                    {msg.role === 'orch' ? 'Orchestrator' : 'Operator'}
                  </span>
                  <span className="dialog-msg-time">
                    {new Date(msg.ts).toLocaleTimeString('en-GB', {
                      hour: '2-digit', minute: '2-digit', second: '2-digit',
                    })}
                  </span>
                </div>
                {msg.isConfirm ? (
                  <div className="dialog-msg-body dialog-confirm-body">
                    <span className="dialog-confirm-token">CONFIRM</span>
                    <span className="dialog-confirm-hint">Engagement approved — starting pipeline</span>
                  </div>
                ) : msg.role === 'orch' ? (
                  <div
                    className="dialog-msg-body dialog-msg-body--md"
                    dangerouslySetInnerHTML={{ __html: marked.parse(msg.text) }}
                  />
                ) : (
                  <div className="dialog-msg-body">{msg.text}</div>
                )}
              </div>
            ))}
          </div>

          <div className="dialog-input-wrap">
            <div className="dialog-input-row">
              <textarea
                className="dialog-textarea"
                rows={2}
                value={input}
                onChange={e => setInput(e.target.value)}
                placeholder="Reply to orchestrator…"
                disabled={sending || confirmed}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(e) }
                }}
              />
              <button
                className="dialog-btn-send"
                onClick={handleSend}
                disabled={sending || !input.trim() || confirmed}
              >
                Send
              </button>
            </div>
            <div className="dialog-proceed-row">
              <span className="dialog-proceed-hint">
                {confirmed
                  ? 'Starting engagement…'
                  : `${selected.size} technique${selected.size !== 1 ? 's' : ''} selected`}
              </span>
              {error && <span className="dialog-error">{error}</span>}
              <button
                className="dialog-btn-proceed"
                onClick={handleConfirm}
                disabled={confirmed || sending || !hasOrchMessage}
              >
                {confirmed ? 'Starting…' : 'Proceed →'}
              </button>
            </div>
          </div>
        </div>

        {/* ── Extensions pane ── */}
        <div className={`dialog-ext-pane${panelOpen ? '' : ' dialog-ext-pane--hidden'}`}>
          <div className="dialog-tabs">
            <button
              className={`dialog-tab${tab === 'objectives' ? ' dialog-tab--active' : ''}`}
              onClick={() => setTab('objectives')}
            >
              Objectives
            </button>
            <button
              className={`dialog-tab${tab === 'techniques' ? ' dialog-tab--active' : ''}`}
              onClick={() => setTab('techniques')}
            >
              Techniques
            </button>
            <button
              className={`dialog-tab${tab === 'tools' ? ' dialog-tab--active' : ''}`}
              onClick={() => setTab('tools')}
            >
              Tools
            </button>
          </div>

          {tab === 'objectives' && (
            <div className="dialog-ext-scroll">
              {OBJECTIVES.map(obj => {
                const techCount = obj.tactic
                  ? TECHNIQUES.filter(t => t.tactic === obj.tactic && t.enabled && selected.has(t.id)).length
                  : 0
                return (
                  <div
                    key={obj.id}
                    className={`dialog-obj-card${obj.enabled ? ' dialog-obj-card--active' : ' dialog-obj-card--locked'}`}
                  >
                    <div className="dialog-obj-status">
                      {obj.enabled
                        ? <span className="dialog-obj-dot" />
                        : <span className="dialog-ext-lock">🔒</span>
                      }
                    </div>
                    <div className="dialog-obj-body">
                      <div className="dialog-obj-header">
                        <span className={`dialog-obj-id${obj.enabled ? '' : ' dialog-obj-id--dim'}`}>{obj.id}</span>
                        <span className={`dialog-obj-name${obj.enabled ? '' : ' dialog-obj-name--dim'}`}>{obj.name}</span>
                        {obj.enabled && techCount > 0 && (
                          <span className="dialog-obj-count">{techCount} technique{techCount !== 1 ? 's' : ''}</span>
                        )}
                      </div>
                      <div className={`dialog-obj-desc${obj.enabled ? '' : ' dialog-obj-desc--dim'}`}>{obj.desc}</div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          {tab === 'techniques' && (
            <div className="dialog-ext-scroll">
              {TACTIC_ORDER.filter(t => tacticGroups[t]).map(tactic => (
                <div key={tactic} className="dialog-tactic-group">
                  <div className="dialog-tactic-label">{tactic}</div>
                  {tacticGroups[tactic].map(tech => (
                    <div
                      key={tech.id}
                      className={[
                        'dialog-ext-card',
                        tech.enabled && selected.has(tech.id) ? 'dialog-ext-card--selected' : '',
                        tech.enabled && !selected.has(tech.id) ? 'dialog-ext-card--enabled' : '',
                        !tech.enabled ? 'dialog-ext-card--locked' : '',
                      ].filter(Boolean).join(' ')}
                      onClick={() => tech.enabled && toggleTechnique(tech.id)}
                    >
                      {tech.enabled ? (
                        <div className={`dialog-ext-check${selected.has(tech.id) ? ' dialog-ext-check--on' : ''}`}>
                          {selected.has(tech.id) ? '✓' : ''}
                        </div>
                      ) : (
                        <div className="dialog-ext-lock">🔒</div>
                      )}
                      <div className="dialog-ext-info">
                        <div className={`dialog-ext-id${!tech.enabled ? ' dialog-ext-id--dim' : ''}`}>{tech.id}</div>
                        <div className={`dialog-ext-name${!tech.enabled ? ' dialog-ext-name--dim' : ''}`}>{tech.name}</div>
                        <div className="dialog-ext-impl">{tech.impl}</div>
                      </div>
                      {tech.enabled && <div className="dialog-ext-badge">recommended</div>}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}

          {tab === 'tools' && (
            <div className="dialog-ext-scroll">
              <div className="dialog-tools-note">
                Read-only · auto-resolved from technique selection
              </div>
              {TOOLS.map(tool => {
                const active = tool.technique ? selected.has(tool.technique) : false
                return (
                  <div key={tool.name} className={`dialog-tool-card${active ? ' dialog-tool-card--active' : ' dialog-tool-card--locked'}`}>
                    <div className={`dialog-tool-dot${active ? ' dialog-tool-dot--on' : ''}`} />
                    <div className="dialog-tool-info">
                      <div className="dialog-tool-name">{tool.name}</div>
                      <div className="dialog-tool-desc">{tool.desc}</div>
                      <div className="dialog-tool-impl">{tool.impl}</div>
                      <div className={`dialog-tool-tech${active ? '' : ' dialog-tool-tech--off'}`}>
                        {tool.technique
                          ? `→ ${tool.technique}${!active ? ' (deselected)' : ''}`
                          : 'not yet supported'}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          <div className="dialog-ext-footer">
            <span><span className="dialog-ext-count">{selected.size}</span> selected</span>
            <span className="dialog-ext-locked">{lockedCount} locked</span>
          </div>
        </div>
      </div>
    </div>
  )
}
