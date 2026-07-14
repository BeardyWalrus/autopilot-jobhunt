import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { absUrl } from '../util.js'

export default function Scan() {
  const [running, setRunning] = useState(false)
  const [lines, setLines] = useState([])
  const [results, setResults] = useState([])
  const [msg, setMsg] = useState(null)
  const [seen, setSeen] = useState(null)
  const [seenUrls, setSeenUrls] = useState(null)  // loaded list (null until "view/edit")
  const [seenTrunc, setSeenTrunc] = useState(false)
  const [seenDirty, setSeenDirty] = useState(false)
  const [seenSaving, setSeenSaving] = useState(false)
  const [hideHandled, setHideHandled] = useState(false)
  const logRef = useRef(null)
  const esRef = useRef(null)
  const pollRef = useRef(null)

  useEffect(() => {
    loadResults()
    loadSeen()
    // Reconnect to a scan on mount so switching tabs doesn't lose it. If one is
    // running we reopen the live stream; if one finished while we were away, we
    // restore its log (the runner keeps the buffer) instead of showing "idle".
    api.scanStatus().then((s) => {
      if (s.running) {
        setRunning(true)
        openStream()  // replays the buffered log, then keeps streaming
      } else if (s.line_count > 0) {
        api.scanLogs().then((r) => setLines(r.lines || [])).catch(() => {})
      }
    }).catch(() => {})
    return () => { esRef.current?.close(); clearInterval(pollRef.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [lines])

  function loadResults() {
    api.results().then((r) => setResults(r.jobs)).catch(() => {})
  }

  async function deleteResult(job) {
    setMsg(null)
    setResults((rs) => rs.filter((r) => r.url !== job.url))  // optimistic
    try {
      await api.deleteResult(job.url)
    } catch (e) {
      setMsg({ err: e.message })
      loadResults()  // resync if the delete didn't take
    }
  }

  async function clearResults() {
    if (!results.length) return
    if (!window.confirm(
      `Delete all ${results.length} result(s)?\n\n` +
      'This clears the current scan results only — your job history is kept, and ' +
      'these jobs stay "seen" so they won\'t re-appear next scan.',
    )) return
    setMsg(null)
    try {
      await api.clearResults()
      setResults([])
    } catch (e) {
      setMsg({ err: e.message })
    }
  }

  function loadSeen() {
    api.scanSeen().then((r) => setSeen(r.seen)).catch(() => {})
  }

  async function forget() {
    if (!window.confirm(
      'Forget the scanner\'s memory of already-seen jobs?\n\n' +
      'The next scan will re-discover and re-score every job. Your saved results ' +
      'are kept — only the "already seen, skip it" list is cleared.',
    )) return
    setMsg(null)
    try {
      const r = await api.scanForget()
      setSeen(r.seen)
      if (seenUrls !== null) setSeenUrls([])  // reflect the clear in the open list
      setSeenDirty(false)
      setMsg({ ok: `Cleared ${r.forgotten} remembered job(s). The next scan starts fresh.` })
    } catch (e) {
      setMsg({ err: e.message })
    }
  }

  async function openSeen() {
    setMsg(null)
    try {
      const r = await api.scanSeenList()
      setSeenUrls(r.urls || [])
      setSeenTrunc(!!r.truncated)
      setSeenDirty(false)
    } catch (e) {
      setMsg({ err: e.message })
    }
  }

  function removeSeenUrl(u) {
    setSeenUrls(seenUrls.filter((x) => x !== u))
    setSeenDirty(true)
  }

  async function saveSeen() {
    setSeenSaving(true)
    setMsg(null)
    try {
      const r = await api.scanSeenSet(seenUrls)
      setSeen(r.seen)
      setSeenDirty(false)
      setMsg({ ok: r.removed ? `Removed ${r.removed} — they'll be re-scanned next time.` : 'Saved.' })
    } catch (e) {
      setMsg({ err: e.message })
    } finally {
      setSeenSaving(false)
    }
  }

  function finishStream(es) {
    es.close()
    if (esRef.current === es) esRef.current = null
    clearInterval(pollRef.current)
    setRunning(false)
    // Pull the authoritative final log + results the stream may have missed.
    api.scanLogs().then((r) => setLines(r.lines || [])).catch(() => {})
    loadResults()
    loadSeen()
  }

  function openStream() {
    esRef.current?.close()
    clearInterval(pollRef.current)
    setLines([])
    let opened = false
    const es = new EventSource('/api/scan/stream')
    esRef.current = es
    // On a reconnect the server replays its whole buffer, so clear first to avoid
    // duplicating the log; the first open keeps the setLines([]) above.
    es.onopen = () => { if (opened) setLines([]); opened = true }
    es.onmessage = (e) => setLines((prev) => [...prev, e.data])
    es.addEventListener('end', () => finishStream(es))
    es.onerror = async () => {
      // A long LLM call can idle the connection long enough for a proxy to drop
      // it. Don't kill the stream — EventSource auto-reconnects. Only finish when
      // the scan has actually ended (no 'end' event will arrive in that case).
      try {
        const s = await api.scanStatus()
        if (!s.running) finishStream(es)
      } catch { /* transient — keep the EventSource open to retry */ }
    }
    // Backstop: if SSE gets wedged, still notice completion within ~15s.
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.scanStatus()
        if (!s.running) finishStream(es)
      } catch { /* ignore */ }
    }, 15000)
  }

  async function setStatus(job, status) {
    setMsg(null)
    const next = job.status === status ? 'new' : status  // click again to undo
    setResults((rs) => rs.map((r) => (r.url === job.url ? { ...r, status: next } : r)))
    try {
      await api.setResultStatus(job.url, next)
    } catch (e) {
      setMsg({ err: e.message })
      loadResults()
    }
  }

  async function start() {
    setMsg(null)
    try {
      await api.scanStart()
      setRunning(true)
      openStream()
    } catch (e) {
      setMsg({ err: e.message })
    }
  }

  async function stop() {
    try {
      await api.scanStop()
    } catch (e) {
      setMsg({ err: e.message })
    }
  }

  const handledCount = results.filter((j) => j.status && j.status !== 'new').length
  const visibleResults = hideHandled
    ? results.filter((j) => !j.status || j.status === 'new')
    : results

  return (
    <div className="stack">
      <div className="card">
        <div className="row between">
          <h2>Scan</h2>
          <div className="row">
            {!running && seen != null && (
              <button className="nowrap" onClick={forget} disabled={!seen}
                title={seen ? 'Clear the seen-jobs memory so the next scan redoes everything'
                            : 'Nothing to forget yet'}>
                Forget scanned history{seen ? ` (${seen})` : ''}
              </button>
            )}
            {running
              ? <button className="danger" onClick={stop}>Stop</button>
              : <button className="primary" onClick={start}>Scan now</button>}
            <span className={running ? 'badge live' : 'badge idle'}>{running ? '● running' : '○ idle'}</span>
          </div>
        </div>
        {msg?.err && <p className="err">{msg.err}</p>}
        {msg?.ok && <p className="ok">{msg.ok}</p>}
        <pre className="log" ref={logRef}>
          {lines.length ? lines.join('\n') : 'No scan output yet. Hit “Scan now”.'}
        </pre>
      </div>

      <div className="card">
        <div className="row between">
          <h2>Previously seen jobs <span className="muted">({seen ?? '…'})</span></h2>
          {seenUrls === null
            ? <button className="link" onClick={openSeen} disabled={!seen}>view / edit</button>
            : <button className="link" onClick={() => { setSeenUrls(null); setSeenDirty(false) }}>hide</button>}
        </div>
        <p className="muted small">
          URLs the scanner remembers and skips. Remove any to have that job re-discovered
          and re-scored on the next scan.
        </p>
        {seenUrls !== null && (
          <>
            {seenUrls.length === 0
              ? <p className="muted center">Nothing remembered.</p>
              : (
                <ul className="seen-list">
                  {seenUrls.map((u) => (
                    <li className="seen-item" key={u}>
                      <a className="url small" href={u} target="_blank" rel="noreferrer">{u}</a>
                      <button className="link danger nowrap" onClick={() => removeSeenUrl(u)}
                        title="Re-scan this job next time">remove</button>
                    </li>
                  ))}
                </ul>
              )}
            {seenTrunc && (
              <p className="muted small">
                Showing the first {seenUrls.length}. Older URLs aren’t listed — use “Forget scanned history” to clear all.
              </p>
            )}
            <div className="actions">
              <button className="primary" onClick={saveSeen} disabled={!seenDirty || seenSaving || running}>
                {seenSaving ? 'Saving…' : 'Save changes'}
              </button>
              {seenDirty && <span className="muted small">unsaved</span>}
              {running && <span className="muted small">stop the scan to edit</span>}
            </div>
          </>
        )}
      </div>

      <div className="card">
        <div className="row between">
          <h2>Results <span className="muted">({visibleResults.length}{handledCount ? ` of ${results.length}` : ''})</span></h2>
          <div className="row">
            {handledCount > 0 && (
              <label className="checkbox nowrap" title="Hide results marked applied or not-a-fit">
                <input type="checkbox" checked={hideHandled} onChange={(e) => setHideHandled(e.target.checked)} />
                Hide handled ({handledCount})
              </label>
            )}
            <button className="link" onClick={loadResults}>refresh</button>
            <button className="link danger" onClick={clearResults} disabled={!results.length}>clear all</button>
          </div>
        </div>
        <p className="muted small">Results persist across scans. Mark each <strong>Applied</strong> or <strong>Not a fit</strong>, or delete it — they stay until you do.</p>
        <div className="tablewrap">
          <table>
            <thead>
              <tr><th>Score</th><th>Company</th><th>Role</th><th>Location</th><th>Stack</th><th>Why</th><th>Status</th><th></th></tr>
            </thead>
            <tbody>
              {visibleResults.map((j, i) => (
                <tr key={j.url || i} className={j.status === 'not_applied' ? 'handled' : ''}>
                  <td><span className={scoreClass(j.score)}>{j.score ?? '—'}</span></td>
                  <td>{j.company}</td>
                  <td>{j.extracted_title || j.title}</td>
                  <td>{j.location_remote || j.location}</td>
                  <td className="small">{j.stack}</td>
                  <td className="small">{j.reason}</td>
                  <td className="nowrap">
                    <button
                      className={j.status === 'applied' ? 'chip on ok' : 'chip'}
                      onClick={() => setStatus(j, 'applied')}
                      title="Mark as applied">✓ Applied</button>
                    <button
                      className={j.status === 'not_applied' ? 'chip on muted-chip' : 'chip'}
                      onClick={() => setStatus(j, 'not_applied')}
                      title="Mark as not a fit">✗ Not a fit</button>
                  </td>
                  <td className="nowrap">
                    {j.url && <a className="apply" href={absUrl(j.url)} target="_blank" rel="noopener noreferrer">Apply ↗</a>}
                    <button className="link danger" onClick={() => deleteResult(j)} title="Remove from results">delete</button>
                  </td>
                </tr>
              ))}
              {results.length === 0 && <tr><td colSpan={8} className="muted center">No results yet — run a scan.</td></tr>}
              {results.length > 0 && visibleResults.length === 0 && (
                <tr><td colSpan={8} className="muted center">All results handled — untick “Hide handled” to see them.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function scoreClass(s) {
  if (s == null) return 'score'
  if (s >= 80) return 'score high'
  if (s >= 60) return 'score mid'
  return 'score low'
}
