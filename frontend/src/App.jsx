import { useEffect, useState } from 'react'
import { api } from './api.js'
import Settings from './components/Settings.jsx'
import Boards from './components/Boards.jsx'
import Resume from './components/Resume.jsx'
import Scan from './components/Scan.jsx'

const TABS = [
  { id: 'scan', label: 'Scan & Results' },
  { id: 'boards', label: 'Job Boards' },
  { id: 'resume', label: 'Resume' },
  { id: 'settings', label: 'Settings' },
]

export default function App() {
  const [tab, setTab] = useState('scan')
  const [health, setHealth] = useState(null)

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ status: 'error' }))
  }, [])

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">◎</span> autopilot<span className="muted">-jobhunt</span>
        </div>
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? 'tab active' : 'tab'}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className="health">
          {health?.status === 'ok' ? (
            <span title={health.project_dir}>● v{health.version}</span>
          ) : (
            <span className="err">● offline</span>
          )}
        </div>
      </header>

      <main className="content">
        {tab === 'scan' && <Scan />}
        {tab === 'boards' && <Boards />}
        {tab === 'resume' && <Resume />}
        {tab === 'settings' && <Settings />}
      </main>
    </div>
  )
}
