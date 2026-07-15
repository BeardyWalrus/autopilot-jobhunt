import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

export default function Resume() {
  const [content, setContent] = useState('')   // saved resume (rendered in view mode)
  const [draft, setDraft] = useState('')        // editable copy (textarea in edit mode)
  const [editing, setEditing] = useState(false)
  const [path, setPath] = useState('')
  const [msg, setMsg] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const fileRef = useRef(null)

  useEffect(() => {
    api.getResume()
      .then((r) => { setContent(r.content); setPath(r.path) })
      .catch((e) => setMsg({ err: e.message }))
      .finally(() => setLoading(false))
  }, [])

  function startEdit() { setDraft(content); setEditing(true); setMsg(null) }
  function cancelEdit() { setEditing(false); setMsg(null) }

  async function save() {
    setSaving(true)
    setMsg(null)
    try {
      await api.putResume(draft)
      setContent(draft)
      setEditing(false)
      setMsg({ ok: 'Resume saved.' })
    } catch (e) {
      setMsg({ err: e.message })
    } finally {
      setSaving(false)
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
      setEditing(false)
      setMsg({ ok: `Uploaded ${file.name}.` })
    } catch (e) {
      setMsg({ err: e.message })
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  if (loading) return <div className="card">Loading resume…</div>

  const hasResume = content.trim().length > 0

  return (
    <div className="stack">
      <div className="card">
        <div className="row between">
          <h2>Resume <span className="muted small">{path}</span></h2>
          <div className="row">
            <input ref={fileRef} type="file" accept=".md,.txt,text/markdown,text/plain" onChange={onUpload} hidden />
            <button onClick={() => fileRef.current?.click()}>Upload file…</button>
            {!editing && (
              <button className="primary" onClick={startEdit}>{hasResume ? 'Edit' : 'Add resume'}</button>
            )}
          </div>
        </div>
        <p className="muted small">Markdown or plain text. This is what every job is scored against.</p>

        {editing ? (
          <>
            <textarea
              className="mono" rows={22} value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="# Your Name&#10;Senior ML Engineer…"
            />
            <div className="actions">
              <button className="primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save resume'}</button>
              <button onClick={cancelEdit} disabled={saving}>Cancel</button>
              {msg?.ok && <span className="ok">{msg.ok}</span>}
              {msg?.err && <span className="err">{msg.err}</span>}
            </div>
          </>
        ) : (
          <>
            {hasResume
              ? <div className="md-view">{renderMarkdown(content)}</div>
              : <p className="muted center">No resume yet — click <strong>Add resume</strong> to write one, or upload a file.</p>}
            {(msg?.ok || msg?.err) && (
              <div className="actions">
                {msg?.ok && <span className="ok">{msg.ok}</span>}
                {msg?.err && <span className="err">{msg.err}</span>}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// --- tiny, dependency-free Markdown renderer -----------------------------------
// Renders to React elements (no dangerouslySetInnerHTML, so no HTML injection).
// Covers the subset resumes actually use: headings, bold/italic/code, links,
// bullet + numbered lists, and horizontal rules. Anything else renders as text.

function renderInline(text) {
  const re = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)|(?:\*|_)([^*_]+)(?:\*|_)/g
  const nodes = []
  let last = 0
  let key = 0
  let m
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index))
    if (m[1] !== undefined) nodes.push(<strong key={key++}>{m[1]}</strong>)
    else if (m[2] !== undefined) nodes.push(<code key={key++}>{m[2]}</code>)
    else if (m[3] !== undefined) nodes.push(<a key={key++} href={m[4]} target="_blank" rel="noopener noreferrer">{m[3]}</a>)
    else if (m[5] !== undefined) nodes.push(<em key={key++}>{m[5]}</em>)
    last = re.lastIndex
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

function renderMarkdown(md) {
  const lines = md.replace(/\r\n/g, '\n').split('\n')
  const blocks = []
  let list = null   // { type: 'ul' | 'ol', items: [] }
  let para = []
  let key = 0

  const flushPara = () => {
    if (para.length) { blocks.push(<p key={key++}>{renderInline(para.join(' '))}</p>); para = [] }
  }
  const flushList = () => {
    if (list) {
      const Tag = list.type
      blocks.push(<Tag key={key++}>{list.items.map((it, i) => <li key={i}>{renderInline(it)}</li>)}</Tag>)
      list = null
    }
  }

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '')
    if (!line.trim()) { flushPara(); flushList(); continue }

    const heading = line.match(/^(#{1,6})\s+(.*)$/)
    if (heading) {
      flushPara(); flushList()
      const Tag = `h${Math.min(heading[1].length, 3)}`
      blocks.push(<Tag key={key++}>{renderInline(heading[2])}</Tag>)
      continue
    }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
      flushPara(); flushList()
      blocks.push(<hr key={key++} />)
      continue
    }
    const ul = line.match(/^\s*[-*+]\s+(.*)$/)
    if (ul) {
      flushPara()
      if (!list || list.type !== 'ul') { flushList(); list = { type: 'ul', items: [] } }
      list.items.push(ul[1])
      continue
    }
    const ol = line.match(/^\s*\d+\.\s+(.*)$/)
    if (ol) {
      flushPara()
      if (!list || list.type !== 'ol') { flushList(); list = { type: 'ol', items: [] } }
      list.items.push(ol[1])
      continue
    }
    flushList()
    para.push(line)
  }
  flushPara()
  flushList()
  return blocks
}
