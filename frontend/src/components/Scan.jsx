import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

export default function Scan() {
  const [running, setRunning] = useState(false)
  const [lines, setLines] = useState([])
  const [results, setResults] = useState([])
  const [msg, setMsg] = useState(null)
  const logRef = useRef(null)
  const esRef = useRef(null)

  useEffect(() => {
    loadResults()
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
    return () => esRef.current?.close()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [lines])

  function loadResults() {
    api.results().then((r) => setResults(r.jobs)).catch(() => {})
  }

  function openStream() {
    esRef.current?.close()
    setLines([])
    const es = new EventSource('/api/scan/stream')
    esRef.current = es
    es.onmessage = (e) => setLines((prev) => [...prev, e.data])
    es.addEventListener('end', () => {
      es.close()
      setRunning(false)
      loadResults()
    })
    es.onerror = () => { es.close(); setRunning(false) }
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

  return (
    <div className="stack">
      <div className="card">
        <div className="row between">
          <h2>Scan</h2>
          <div className="row">
            {running
              ? <button className="danger" onClick={stop}>Stop</button>
              : <button className="primary" onClick={start}>Scan now</button>}
            <span className={running ? 'badge live' : 'badge idle'}>{running ? '● running' : '○ idle'}</span>
          </div>
        </div>
        {msg?.err && <p className="err">{msg.err}</p>}
        <pre className="log" ref={logRef}>
          {lines.length ? lines.join('\n') : 'No scan output yet. Hit “Scan now”.'}
        </pre>
      </div>

      <div className="card">
        <div className="row between">
          <h2>Results <span className="muted">({results.length})</span></h2>
          <button className="link" onClick={loadResults}>refresh</button>
        </div>
        <div className="tablewrap">
          <table>
            <thead>
              <tr><th>Score</th><th>Company</th><th>Role</th><th>Location</th><th>Stack</th><th>Why</th><th></th></tr>
            </thead>
            <tbody>
              {results.map((j, i) => (
                <tr key={i}>
                  <td><span className={scoreClass(j.score)}>{j.score ?? '—'}</span></td>
                  <td>{j.company}</td>
                  <td>{j.extracted_title || j.title}</td>
                  <td>{j.location_remote || j.location}</td>
                  <td className="small">{j.stack}</td>
                  <td className="small">{j.reason}</td>
                  <td>{j.url && <a href={j.url} target="_blank" rel="noreferrer">Apply</a>}</td>
                </tr>
              ))}
              {results.length === 0 && <tr><td colSpan={7} className="muted center">No results yet — run a scan.</td></tr>}
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
