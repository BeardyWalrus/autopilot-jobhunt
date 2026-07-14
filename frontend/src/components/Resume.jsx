import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

export default function Resume() {
  const [content, setContent] = useState('')
  const [path, setPath] = useState('')
  const [msg, setMsg] = useState(null)
  const [loading, setLoading] = useState(true)
  const fileRef = useRef(null)

  useEffect(() => {
    api.getResume()
      .then((r) => { setContent(r.content); setPath(r.path) })
      .catch((e) => setMsg({ err: e.message }))
      .finally(() => setLoading(false))
  }, [])

  async function save() {
    setMsg(null)
    try {
      await api.putResume(content)
      setMsg({ ok: 'Resume saved.' })
    } catch (e) {
      setMsg({ err: e.message })
    }
  }

  async function onUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setMsg(null)
    try {
      await api.uploadResume(file)
      const r = await api.getResume()
      setContent(r.content)
      setMsg({ ok: `Uploaded ${file.name}.` })
    } catch (e) {
      setMsg({ err: e.message })
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  if (loading) return <div className="card">Loading resume…</div>

  return (
    <div className="stack">
      <div className="card">
        <div className="row between">
          <h2>Resume <span className="muted small">{path}</span></h2>
          <div className="row">
            <input ref={fileRef} type="file" accept=".md,.txt,text/markdown,text/plain" onChange={onUpload} hidden />
            <button onClick={() => fileRef.current?.click()}>Upload file…</button>
          </div>
        </div>
        <p className="muted small">Markdown or plain text. This is what every job is scored against.</p>
        <textarea className="mono" rows={22} value={content} onChange={(e) => setContent(e.target.value)} placeholder="# Your Name&#10;Senior ML Engineer…" />
      </div>

      <div className="actions">
        <button className="primary" onClick={save}>Save resume</button>
        {msg?.ok && <span className="ok">{msg.ok}</span>}
        {msg?.err && <span className="err">{msg.err}</span>}
      </div>
    </div>
  )
}
