import { useEffect, useState } from 'react'
import { api } from '../api.js'

const PROVIDERS = ['openrouter', 'ollama', 'anthropic', 'claude_cli']

export default function Settings() {
  const [cfg, setCfg] = useState(null)
  const [sched, setSched] = useState({ enabled: false, time: '02:00' })
  const [health, setHealth] = useState(null)
  const [msg, setMsg] = useState(null)
  const [saving, setSaving] = useState(false)
  const [ollamaModels, setOllamaModels] = useState([])
  const [ollamaStatus, setOllamaStatus] = useState(null)
  const [testingOllama, setTestingOllama] = useState(false)

  useEffect(() => {
    api.getConfig().then((r) => {
      setCfg(r.config)
      // Auto-populate the Ollama model list if that's the active provider.
      if (r.config.llm_provider === 'ollama') testOllama(r.config.ollama_base_url, true)
    }).catch((e) => setMsg({ err: e.message }))
    api.getSchedule().then((s) => setSched({ enabled: s.enabled, time: s.time })).catch(() => {})
    api.health().then(setHealth).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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

  const provider = cfg.llm_provider || 'openrouter'
  const ollamaOptions = Array.from(new Set([...ollamaModels, cfg.ollama_model].filter(Boolean)))

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
      </div>

      <div className="card">
        <h2>LLM provider</h2>
        <div className="grid">
          <Field label="Provider">
            <select value={provider} onChange={(e) => set('llm_provider', e.target.value)}>
              {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </Field>
          {provider === 'openrouter' && (
            <Field label="OpenRouter model"><input value={cfg.openrouter_model || ''} onChange={(e) => set('openrouter_model', e.target.value)} /></Field>
          )}
          {provider === 'ollama' && (
            <>
              <Field label="Ollama model" hint="installed models — Test to refresh">
                <select value={cfg.ollama_model || ''} onChange={(e) => set('ollama_model', e.target.value)}>
                  {!cfg.ollama_model && (
                    <option value="">{ollamaModels.length ? '— select a model —' : '— Test to list models —'}</option>
                  )}
                  {ollamaOptions.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </Field>
              <Field label="Ollama base URL">
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
          {provider === 'anthropic' && (
            <Field label="Anthropic model"><input value={cfg.anthropic_model || ''} onChange={(e) => set('anthropic_model', e.target.value)} /></Field>
          )}
          {provider === 'claude_cli' && (
            <Field label="Claude CLI model" hint="sonnet / opus / haiku (blank = default)"><input value={cfg.claude_cli_model || ''} onChange={(e) => set('claude_cli_model', e.target.value)} /></Field>
          )}
        </div>
      </div>

      <div className="card">
        <h2>API keys</h2>
        <p className="muted small">Stored locally in config.json. Leave blank to use a .env file instead.</p>
        <div className="grid">
          <Field label="TinyFish"><input type="password" value={cfg.tinyfish_api_key || ''} onChange={(e) => set('tinyfish_api_key', e.target.value)} /></Field>
          {provider === 'openrouter' && <Field label="OpenRouter"><input type="password" value={cfg.openrouter_api_key || ''} onChange={(e) => set('openrouter_api_key', e.target.value)} /></Field>}
          {provider === 'anthropic' && <Field label="Anthropic"><input type="password" value={cfg.anthropic_api_key || ''} onChange={(e) => set('anthropic_api_key', e.target.value)} /></Field>}
        </div>
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
