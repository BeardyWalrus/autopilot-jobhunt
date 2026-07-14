import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

const PROVIDERS = ['openrouter', 'ollama', 'anthropic', 'claude_cli']
const LABELS = {
  openrouter: { name: 'OpenRouter', note: 'hosted free tier + paid models' },
  ollama: { name: 'Ollama', note: 'local — no key, no rate limits' },
  anthropic: { name: 'Anthropic', note: 'Claude API (requires key)' },
  claude_cli: { name: 'Claude Code CLI', note: 'uses your local claude auth' },
}
// config.json keys owned by each provider — used to decide which providers are
// "in use" (any value set) and to clear a provider when it's removed.
const PROVIDER_KEYS = {
  openrouter: ['openrouter_model', 'openrouter_api_key', 'openrouter_fallback_models'],
  ollama: ['ollama_model', 'ollama_base_url', 'ollama_api_key'],
  anthropic: ['anthropic_model', 'anthropic_api_key'],
  claude_cli: ['claude_cli_model'],
}

function isConfigured(cfg, p) {
  return PROVIDER_KEYS[p].some((k) => {
    const v = cfg[k]
    return Array.isArray(v) ? v.length > 0 : !!v
  })
}

export default function Settings() {
  const [cfg, setCfg] = useState(null)
  const [sched, setSched] = useState({ enabled: false, time: '02:00' })
  const [health, setHealth] = useState(null)
  const [msg, setMsg] = useState(null)
  const [saving, setSaving] = useState(false)
  const [ollamaModels, setOllamaModels] = useState([])
  const [ollamaStatus, setOllamaStatus] = useState(null)
  const [testingOllama, setTestingOllama] = useState(false)
  const [visible, setVisible] = useState([])  // provider cards currently shown
  const [addPick, setAddPick] = useState('')
  const [stLog, setStLog] = useState(null)     // search-terms suggestion log
  const [stRunning, setStRunning] = useState(false)
  const esRef = useRef(null)
  const stLogRef = useRef(null)
  const tokenRunRef = useRef(false)

  useEffect(() => {
    api.getConfig().then((r) => {
      setCfg(r.config)
      // Show only providers in use: the active one plus any that have config set.
      const active = r.config.llm_provider || 'openrouter'
      setVisible(PROVIDERS.filter((p) => p === active || isConfigured(r.config, p)))
      // Auto-populate the Ollama model list if that's the active provider.
      if (r.config.llm_provider === 'ollama') testOllama(r.config.ollama_base_url, true)
    }).catch((e) => setMsg({ err: e.message }))
    api.getSchedule().then((s) => setSched({ enabled: s.enabled, time: s.time })).catch(() => {})
    api.health().then(setHealth).catch(() => {})
    // Reconnect to a search-terms suggestion still running (or just finished), so
    // navigating away and back doesn't lose it — the job runs on the backend.
    api.jobsResult().then((r) => {
      if (r.name !== 'search-terms') return
      if (r.running) { setStLog(''); setStRunning(true); attachStream() }
      else if (r.ok && r.result?.kind === 'search_terms') applyTerms(r.result)
    }).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => () => esRef.current?.close(), [])

  useEffect(() => {
    if (stLogRef.current) stLogRef.current.scrollTop = stLogRef.current.scrollHeight
  }, [stLog])

  async function testOllama(baseUrl, silent = false) {
    setTestingOllama(true)
    if (!silent) setOllamaStatus(null)
    try {
      const r = await api.testOllama(baseUrl || '')
      setOllamaModels(r.models || [])
      setOllamaStatus(r.ok
        ? { ok: `Connected — ${r.models.length} model${r.models.length === 1 ? '' : 's'} available` }
        : { err: r.error })
    } catch (e) {
      setOllamaStatus({ err: e.message })
    } finally {
      setTestingOllama(false)
    }
  }

  if (!cfg) return <div className="card">Loading settings…</div>

  const cand = cfg.candidate || {}
  const tg = cfg.telegram || {}
  const set = (key, val) => setCfg({ ...cfg, [key]: val })
  const setCand = (key, val) => setCfg({ ...cfg, candidate: { ...cand, [key]: val } })
  const setTg = (key, val) => setCfg({ ...cfg, telegram: { ...tg, [key]: val } })

  async function save() {
    setSaving(true)
    setMsg(null)
    try {
      await api.putConfig(cfg)
      await api.putSchedule(sched.enabled, sched.time)
      setMsg({ ok: 'Saved. New settings apply to the next scan.' })
    } catch (e) {
      setMsg({ err: e.message })
    } finally {
      setSaving(false)
    }
  }

  function applyTerms(res) {
    setCfg((c) => ({
      ...c,
      candidate: {
        ...(c.candidate || {}),
        ...(res.search_keywords ? { search_keywords: res.search_keywords } : {}),
        ...(res.search_seniority ? { search_seniority: res.search_seniority } : {}),
      },
    }))
    setMsg(res.search_keywords || res.search_seniority
      ? { ok: 'Suggested terms filled in below — review and Save settings to apply.' }
      : { err: 'No terms came back — try again.' })
  }

  // Open the shared job SSE stream — used to start a fresh suggestion and to
  // reconnect to a running one after navigating back (it replays the buffer).
  function attachStream() {
    esRef.current?.close()
    const es = new EventSource('/api/companies/jobs/stream')
    esRef.current = es
    tokenRunRef.current = false
    es.onmessage = (ev) =>
      setStLog((prev) => { tokenRunRef.current = false; return (prev ? prev + '\n' : '') + ev.data })
    es.addEventListener('token', (ev) =>
      setStLog((prev) => {
        const sep = tokenRunRef.current ? '' : prev && !prev.endsWith('\n') ? '\n' : ''
        tokenRunRef.current = true
        return (prev || '') + sep + ev.data
      }),
    )
    es.addEventListener('end', async () => {
      es.close()
      setStRunning(false)
      try {
        const r = await api.jobsResult()
        if (r.ok === false) { setMsg({ err: r.error || 'Suggestion failed — see the log above.' }); return }
        if (r.result?.kind === 'search_terms') applyTerms(r.result)
      } catch (e) {
        setMsg({ err: e.message })
      }
    })
    es.onerror = () => { es.close(); setStRunning(false) }
  }

  async function suggestTerms() {
    setMsg(null)
    setStLog('')
    setStRunning(true)
    try {
      await api.suggestSearchTerms()
    } catch (e) {
      setStRunning(false)
      setStLog(null)
      setMsg({ err: e.message })
      return
    }
    attachStream()
  }

  const provider = cfg.llm_provider || 'openrouter'
  const ollamaOptions = Array.from(new Set([...ollamaModels, cfg.ollama_model].filter(Boolean)))
  const hiddenProviders = PROVIDERS.filter((p) => !visible.includes(p))

  function addProvider(p) {
    if (!p || visible.includes(p)) return
    setVisible([...visible, p])
    setAddPick('')
    if (p === 'ollama' && !ollamaModels.length) testOllama(cfg.ollama_base_url, true)
  }

  function removeProvider(p) {
    if (p === provider) return  // can't remove the active provider
    const next = { ...cfg }
    PROVIDER_KEYS[p].forEach((k) => delete next[k])  // clear its config so it stays removed
    setCfg(next)
    setVisible(visible.filter((x) => x !== p))
  }

  return (
    <div className="stack">
      <div className="card">
        <h2>Candidate</h2>
        <div className="grid">
          <Field label="Name"><input value={cand.name || ''} onChange={(e) => setCand('name', e.target.value)} /></Field>
          <Field label="Min score" hint="0–100 threshold to surface a job">
            <input type="number" value={cand.min_score ?? 60} onChange={(e) => setCand('min_score', Number(e.target.value))} />
          </Field>
          <Field label="Top N" hint="how many top matches to notify">
            <input type="number" value={cand.top_n ?? 5} onChange={(e) => setCand('top_n', Number(e.target.value))} />
          </Field>
        </div>
        <Field label="Profile"><textarea rows={2} value={cand.profile || ''} onChange={(e) => setCand('profile', e.target.value)} /></Field>
        <Field label="Seeking"><input value={cand.seeking || ''} onChange={(e) => setCand('seeking', e.target.value)} /></Field>
        <Field label="Not suitable"><input value={cand.not_suitable || ''} onChange={(e) => setCand('not_suitable', e.target.value)} /></Field>

        <h3 className="subhead">Job search terms</h3>
        <p className="muted small">
          These build the query run against each company (<span className="mono">site:domain (seniority) (keywords)</span>).
          Use <span className="mono">OR</span> and quote phrases. Leave blank to use the ML/data-science defaults.
        </p>
        <div className="row">
          <button type="button" className="suggest-btn nowrap" onClick={suggestTerms} disabled={stRunning}>
            {stRunning ? 'Working…' : '✨  Suggest from my résumé'}
          </button>
          <span className="muted small">Uses your résumé + profile to fill the fields below — you can edit before saving.</span>
        </div>
        {stLog !== null && (
          <div className="joblog-wrap">
            <div className="row between">
              <span className="muted small">{stRunning ? 'Thinking…' : 'Log'}</span>
              {!stRunning && <button type="button" className="link" onClick={() => setStLog(null)}>hide log</button>}
            </div>
            <pre className="log joblog" ref={stLogRef}>{stLog || 'Starting…'}</pre>
          </div>
        )}
        <Field label="Search keywords" hint="role titles / skills to search for">
          <textarea rows={2} value={cand.search_keywords || ''}
            onChange={(e) => setCand('search_keywords', e.target.value)}
            placeholder={'"data scientist" OR "ML engineer" OR "AI engineer" OR MLOps'} />
        </Field>
        <Field label="Search seniority" hint="seniority levels to match">
          <input value={cand.search_seniority || ''}
            onChange={(e) => setCand('search_seniority', e.target.value)}
            placeholder="senior OR staff OR principal OR lead" />
        </Field>
      </div>

      <div className="card">
        <h2>LLM providers</h2>
        <p className="muted small">Set up any providers you use, then pick the one to use for scoring, drafting, and suggestions.</p>
        <div className="providers">
          {visible.map((p) => (
            <div key={p} className={provider === p ? 'provider active' : 'provider'}>
              <label className="provider-head">
                <input
                  type="radio"
                  name="llm_provider"
                  checked={provider === p}
                  onChange={() => {
                    set('llm_provider', p)
                    if (p === 'ollama' && !ollamaModels.length) testOllama(cfg.ollama_base_url, true)
                  }}
                />
                <span className="provider-name">{LABELS[p].name}</span>
                <span className="muted small">{LABELS[p].note}</span>
                {provider === p
                  ? <span className="badge live">active</span>
                  : <button type="button" className="link danger provider-remove" onClick={() => removeProvider(p)}>remove</button>}
              </label>

              <div className="provider-body grid">
                {p === 'openrouter' && (
                  <>
                    <Field label="Model"><input value={cfg.openrouter_model || ''} onChange={(e) => set('openrouter_model', e.target.value)} placeholder="meta-llama/llama-3.3-70b-instruct:free" /></Field>
                    <Field label="API key"><input type="password" value={cfg.openrouter_api_key || ''} onChange={(e) => set('openrouter_api_key', e.target.value)} /></Field>
                    <Field label="Fallback models" hint="comma-separated, tried in order">
                      <input
                        value={(cfg.openrouter_fallback_models || []).join(', ')}
                        onChange={(e) => set('openrouter_fallback_models', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))}
                      />
                    </Field>
                  </>
                )}
                {p === 'ollama' && (
                  <>
                    <Field label="Model" hint="installed models — Test to refresh">
                      <select value={cfg.ollama_model || ''} onChange={(e) => set('ollama_model', e.target.value)}>
                        {!cfg.ollama_model && <option value="">{ollamaModels.length ? '— select a model —' : '— Test to list models —'}</option>}
                        {ollamaOptions.map((m) => <option key={m} value={m}>{m}</option>)}
                      </select>
                    </Field>
                    <Field label="Base URL">
                      <div className="row">
                        <input value={cfg.ollama_base_url || ''} onChange={(e) => set('ollama_base_url', e.target.value)} placeholder="http://localhost:11434/v1" />
                        <button type="button" className="nowrap" onClick={() => testOllama(cfg.ollama_base_url)} disabled={testingOllama}>
                          {testingOllama ? 'Testing…' : 'Test'}
                        </button>
                      </div>
                      {ollamaStatus?.ok && <span className="ok small">✓ {ollamaStatus.ok}</span>}
                      {ollamaStatus?.err && <span className="err small">✗ {ollamaStatus.err}</span>}
                    </Field>
                  </>
                )}
                {p === 'anthropic' && (
                  <>
                    <Field label="Model"><input value={cfg.anthropic_model || ''} onChange={(e) => set('anthropic_model', e.target.value)} placeholder="claude-haiku-4-5-20251001" /></Field>
                    <Field label="API key"><input type="password" value={cfg.anthropic_api_key || ''} onChange={(e) => set('anthropic_api_key', e.target.value)} /></Field>
                  </>
                )}
                {p === 'claude_cli' && (
                  <Field label="Model" hint="sonnet / opus / haiku (blank = default)"><input value={cfg.claude_cli_model || ''} onChange={(e) => set('claude_cli_model', e.target.value)} /></Field>
                )}
              </div>
            </div>
          ))}
        </div>

        {hiddenProviders.length > 0 && (
          <div className="row add-provider">
            <select value={addPick} onChange={(e) => setAddPick(e.target.value)}>
              <option value="">Add a provider…</option>
              {hiddenProviders.map((p) => <option key={p} value={p}>{LABELS[p].name}</option>)}
            </select>
            <button type="button" className="nowrap" disabled={!addPick} onClick={() => addProvider(addPick)}>Add</button>
          </div>
        )}
      </div>

      <div className="card">
        <h2>API keys</h2>
        <p className="muted small">Stored locally in config.json. Leave blank to use a .env file instead. (Provider keys live with each provider above.)</p>
        <Field label="TinyFish — job discovery"><input type="password" value={cfg.tinyfish_api_key || ''} onChange={(e) => set('tinyfish_api_key', e.target.value)} /></Field>
      </div>

      <div className="card">
        <h2>Diagnostics</h2>
        <Field label="Scan log level" hint="DEBUG shows per-URL/per-job detail and raw LLM output in the scan log">
          <select value={cfg.log_level || 'INFO'} onChange={(e) => set('log_level', e.target.value)}>
            <option value="INFO">INFO — normal progress</option>
            <option value="DEBUG">DEBUG — verbose (troubleshooting)</option>
          </select>
        </Field>
        <p className="muted small">The full DEBUG log is always written to <span className="mono">scan.log</span> in your project directory, regardless of this setting.</p>
      </div>

      <div className="card">
        <h2>Telegram (optional)</h2>
        <div className="grid">
          <Field label="Bot token"><input type="password" value={tg.token || ''} onChange={(e) => setTg('token', e.target.value)} /></Field>
          <Field label="Chat ID"><input value={tg.chat_id || ''} onChange={(e) => setTg('chat_id', e.target.value)} /></Field>
        </div>
      </div>

      <div className="card">
        <h2>Schedule</h2>
        <div className="row">
          <label className="checkbox">
            <input type="checkbox" checked={sched.enabled} onChange={(e) => setSched({ ...sched, enabled: e.target.checked })} />
            Run a scan automatically every day
          </label>
          <Field label="At (24h)">
            <input type="time" value={sched.time} onChange={(e) => setSched({ ...sched, time: e.target.value })} />
          </Field>
        </div>
      </div>

      <div className="actions">
        <button className="primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save settings'}</button>
        {msg?.ok && <span className="ok">{msg.ok}</span>}
        {msg?.err && <span className="err">{msg.err}</span>}
      </div>

      <div className="card about">
        <h2>About</h2>
        <div className="kv"><span className="muted">Server version</span><span className="mono">{health ? `v${health.version}` : '…'}</span></div>
        <div className="kv"><span className="muted">Project directory</span><span className="mono small">{health?.project_dir || '…'}</span></div>
      </div>
    </div>
  )
}

function Field({ label, hint, children }) {
  return (
    <label className="field">
      <span className="label">{label}{hint && <em className="hint"> — {hint}</em>}</span>
      {children}
    </label>
  )
}
