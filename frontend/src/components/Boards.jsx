import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'

const BLANK = { name: '', careers_url: '', search_domain: '', location: '', region: '' }

export default function Boards() {
  const [companies, setCompanies] = useState(null)
  const [q, setQ] = useState('')
  const [region, setRegion] = useState('all')
  const [draft, setDraft] = useState(BLANK)
  const [msg, setMsg] = useState(null)
  const [dirty, setDirty] = useState(false)
  const [suggestions, setSuggestions] = useState(null)
  const [flagged, setFlagged] = useState(null)
  const [showDisabled, setShowDisabled] = useState(false)
  const [jobLog, setJobLog] = useState(null)
  const [jobRunning, setJobRunning] = useState(false)
  const esRef = useRef(null)
  const logRef = useRef(null)

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [jobLog])

  useEffect(() => () => esRef.current?.close(), [])

  useEffect(() => {
    api.getCompanies().then((r) => setCompanies(r.companies)).catch((e) => setMsg({ err: e.message }))
  }, [])

  const regions = useMemo(
    () => ['all', ...Array.from(new Set((companies || []).map((c) => c.region).filter(Boolean))).sort()],
    [companies],
  )

  const filtered = useMemo(() => {
    if (!companies) return []
    const needle = q.toLowerCase()
    return companies
      .map((c, i) => ({ c, i }))
      .filter(({ c }) => showDisabled || c.enabled !== false)  // hide "off" boards by default
      .filter(({ c }) => region === 'all' || c.region === region)
      .filter(({ c }) => !needle || `${c.name} ${c.search_domain} ${c.location}`.toLowerCase().includes(needle))
  }, [companies, q, region, showDisabled])

  if (!companies) return <div className="card">Loading job boards…</div>

  const activeCount = companies.filter((c) => c.enabled !== false).length

  function removeAt(idx) {
    setCompanies(companies.filter((_, i) => i !== idx))
    setDirty(true)
  }

  function toggleAt(idx) {
    setCompanies(companies.map((c, i) => (i === idx ? { ...c, enabled: c.enabled === false } : c)))
    setDirty(true)
  }

  function addDraft() {
    if (!draft.name || !draft.careers_url || !draft.search_domain) {
      setMsg({ err: 'Name, careers URL, and search domain are required.' })
      return
    }
    setCompanies([...companies, draft])
    setDraft(BLANK)
    setDirty(true)
    setMsg(null)
  }

  async function save() {
    setMsg(null)
    try {
      const r = await api.putCompanies(companies)
      setCompanies(r.companies)
      setDirty(false)
      setMsg({ ok: `Saved ${r.count} job boards.` })
    } catch (e) {
      setMsg({ err: e.message })
    }
  }

  async function runJob(kind) {
    setMsg(null)
    setSuggestions(null)
    setFlagged(null)
    setJobLog([])
    setJobRunning(true)
    try {
      if (kind === 'suggest') await api.suggestStart(8)
      else await api.reviewStart()
    } catch (e) {
      setJobRunning(false)
      setJobLog(null)
      setMsg({ err: e.message })
      return
    }
    esRef.current?.close()
    const es = new EventSource('/api/companies/jobs/stream')
    esRef.current = es
    es.onmessage = (ev) => setJobLog((prev) => [...(prev || []), ev.data])
    es.addEventListener('end', async () => {
      es.close()
      setJobRunning(false)
      try {
        const r = await api.jobsResult()
        if (r.ok === false) {
          setMsg({ err: r.error || 'The job failed — see the log above.' })
          return
        }
        const res = r.result || {}
        if (res.kind === 'suggest') {
          setSuggestions(res.suggestions || [])
          if (!res.suggestions?.length) setMsg({ err: 'No suggestions came back — try again.' })
        } else if (res.kind === 'review') {
          setFlagged(res.flagged || [])
          if (!res.flagged?.length) setMsg({ ok: `Reviewed ${res.reviewed} companies — none look like a poor fit.` })
        }
      } catch (e) {
        setMsg({ err: e.message })
      }
    })
    es.onerror = () => {
      es.close()
      setJobRunning(false)
    }
  }

  function addSuggestion(s) {
    setCompanies([...companies, {
      name: s.name, careers_url: s.careers_url, search_domain: s.search_domain,
      location: s.location, region: s.region,
    }])
    setDirty(true)
    setSuggestions(suggestions.filter((x) => x !== s))
  }

  function findIdx(f) {
    return companies.findIndex(
      (c) => (f.search_domain && c.search_domain === f.search_domain) || c.name === f.name,
    )
  }

  function disableFlagged(f) {
    const idx = findIdx(f)
    if (idx < 0) return
    setCompanies(companies.map((c, i) => (i === idx ? { ...c, enabled: false } : c)))
    setDirty(true)
    setFlagged(flagged.filter((x) => x !== f))
  }

  function removeFlagged(f) {
    const idx = findIdx(f)
    if (idx < 0) return
    setCompanies(companies.filter((_, i) => i !== idx))
    setDirty(true)
    setFlagged(flagged.filter((x) => x !== f))
  }

  return (
    <div className="stack">
      <div className="card">
        <div className="row between">
          <h2>Job boards <span className="muted">({activeCount} on / {companies.length})</span></h2>
          <div className="row">
            <input placeholder="Search name / domain / location" value={q} onChange={(e) => setQ(e.target.value)} />
            <select value={region} onChange={(e) => setRegion(e.target.value)}>
              {regions.map((r) => <option key={r} value={r}>{r === 'all' ? 'All regions' : r}</option>)}
            </select>
            <label className="checkbox nowrap" title="Disabled boards are hidden by default">
              <input type="checkbox" checked={showDisabled} onChange={(e) => setShowDisabled(e.target.checked)} />
              Show off ({companies.length - activeCount})
            </label>
          </div>
        </div>

        <div className="board-actions">
          <button className="suggest-btn" onClick={() => runJob('suggest')} disabled={jobRunning}>
            {jobRunning ? 'Working…' : '✨  Suggest companies from my résumé'}
          </button>
          <button className="review-btn" onClick={() => runJob('review')} disabled={jobRunning}>
            {jobRunning ? 'Working…' : '🧹  Review my list for poor fits'}
          </button>
        </div>

        {jobLog && (
          <div className="joblog-wrap">
            <div className="row between">
              <span className="muted small">{jobRunning ? 'Running…' : 'Log'}</span>
              {!jobRunning && <button className="link" onClick={() => setJobLog(null)}>hide log</button>}
            </div>
            <pre className="log joblog" ref={logRef}>
              {jobLog.length ? jobLog.join('\n') : 'Starting…'}
            </pre>
          </div>
        )}

        {flagged && flagged.length > 0 && (
          <div className="suggestions flagged">
            <div className="row between">
              <h3>Poor-fit companies <span className="muted small">— disable to keep for later, or remove</span></h3>
              <button className="link" onClick={() => setFlagged(null)}>dismiss</button>
            </div>
            {flagged.map((f, i) => (
              <div className="suggestion" key={i}>
                <div className="sug-main">
                  <div><strong>{f.name}</strong> <span className="muted small">{f.search_domain}</span></div>
                  {f.reason && <div className="muted small">{f.reason}</div>}
                </div>
                <div className="row">
                  <button onClick={() => disableFlagged(f)}>Disable</button>
                  <button className="danger" onClick={() => removeFlagged(f)}>Remove</button>
                </div>
              </div>
            ))}
          </div>
        )}

        {suggestions && suggestions.length > 0 && (
          <div className="suggestions">
            <div className="row between">
              <h3>Suggested for you <span className="muted small">— best-guess URLs, review before saving</span></h3>
              <button className="link" onClick={() => setSuggestions(null)}>dismiss</button>
            </div>
            {suggestions.map((s, i) => (
              <div className="suggestion" key={i}>
                <div className="sug-main">
                  <div><strong>{s.name}</strong> <span className="muted small">{s.region} · {s.location}</span></div>
                  <div className="url small"><a href={s.careers_url} target="_blank" rel="noreferrer">{s.careers_url || s.search_domain}</a></div>
                  {s.reason && <div className="muted small">{s.reason}</div>}
                </div>
                {s.exists
                  ? <span className="muted small">already tracked</span>
                  : <button onClick={() => addSuggestion(s)}>Add</button>}
              </div>
            ))}
          </div>
        )}

        <div className="tablewrap">
          <table>
            <thead>
              <tr><th>On</th><th>Company</th><th>Careers URL</th><th>Search domain</th><th>Location</th><th>Region</th><th></th></tr>
            </thead>
            <tbody>
              {filtered.map(({ c, i }) => (
                <tr key={i} className={c.enabled === false ? 'disabled' : ''}>
                  <td>
                    <label className="switch" title={c.enabled === false ? 'Disabled — skipped on scans' : 'Enabled'}>
                      <input type="checkbox" checked={c.enabled !== false} onChange={() => toggleAt(i)} />
                    </label>
                  </td>
                  <td>{c.name}</td>
                  <td className="url"><a href={c.careers_url} target="_blank" rel="noreferrer">{c.careers_url}</a></td>
                  <td>{c.search_domain}</td>
                  <td>{c.location}</td>
                  <td>{c.region}</td>
                  <td><button className="link danger" onClick={() => removeAt(i)}>remove</button></td>
                </tr>
              ))}
              {filtered.length === 0 && <tr><td colSpan={7} className="muted center">No matches.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2>Add a job board</h2>
        <div className="grid add">
          <input placeholder="Company name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          <input placeholder="https://company.com/careers" value={draft.careers_url} onChange={(e) => setDraft({ ...draft, careers_url: e.target.value })} />
          <input placeholder="company.com" value={draft.search_domain} onChange={(e) => setDraft({ ...draft, search_domain: e.target.value })} />
          <input placeholder="Location" value={draft.location} onChange={(e) => setDraft({ ...draft, location: e.target.value })} />
          <input placeholder="Region (EU/NA/…)" value={draft.region} onChange={(e) => setDraft({ ...draft, region: e.target.value })} />
          <button onClick={addDraft}>Add</button>
        </div>
      </div>

      <div className="actions">
        <button className="primary" onClick={save} disabled={!dirty}>{dirty ? 'Save changes' : 'Saved'}</button>
        {msg?.ok && <span className="ok">{msg.ok}</span>}
        {msg?.err && <span className="err">{msg.err}</span>}
      </div>
    </div>
  )
}
