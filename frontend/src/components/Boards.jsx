import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'

const BLANK = { name: '', careers_url: '', search_domain: '', location: '', region: '' }

export default function Boards() {
  const [companies, setCompanies] = useState(null)
  const [q, setQ] = useState('')
  const [region, setRegion] = useState('all')
  const [draft, setDraft] = useState(BLANK)
  const [msg, setMsg] = useState(null)
  const [dirty, setDirty] = useState(false)

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
      .filter(({ c }) => region === 'all' || c.region === region)
      .filter(({ c }) => !needle || `${c.name} ${c.search_domain} ${c.location}`.toLowerCase().includes(needle))
  }, [companies, q, region])

  if (!companies) return <div className="card">Loading job boards…</div>

  function removeAt(idx) {
    setCompanies(companies.filter((_, i) => i !== idx))
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

  return (
    <div className="stack">
      <div className="card">
        <div className="row between">
          <h2>Job boards <span className="muted">({companies.length})</span></h2>
          <div className="row">
            <input placeholder="Search name / domain / location" value={q} onChange={(e) => setQ(e.target.value)} />
            <select value={region} onChange={(e) => setRegion(e.target.value)}>
              {regions.map((r) => <option key={r} value={r}>{r === 'all' ? 'All regions' : r}</option>)}
            </select>
          </div>
        </div>

        <div className="tablewrap">
          <table>
            <thead>
              <tr><th>Company</th><th>Careers URL</th><th>Search domain</th><th>Location</th><th>Region</th><th></th></tr>
            </thead>
            <tbody>
              {filtered.map(({ c, i }) => (
                <tr key={i}>
                  <td>{c.name}</td>
                  <td className="url"><a href={c.careers_url} target="_blank" rel="noreferrer">{c.careers_url}</a></td>
                  <td>{c.search_domain}</td>
                  <td>{c.location}</td>
                  <td>{c.region}</td>
                  <td><button className="link danger" onClick={() => removeAt(i)}>remove</button></td>
                </tr>
              ))}
              {filtered.length === 0 && <tr><td colSpan={6} className="muted center">No matches.</td></tr>}
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
