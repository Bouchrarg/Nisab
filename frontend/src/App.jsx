import { useCallback, useEffect, useState } from 'react'
import './App.css'
import GlobalCopilot from './GlobalCopilot'
import Sidebar from './components/layout/Sidebar'
import Topbar from './components/layout/Topbar'
import DashboardPage from './pages/DashboardPage'
import AuditPage from './pages/AuditPage'
import CalendarPage from './pages/CalendarPage'
import ChatPage from './pages/ChatPage'
import OdooPage from './pages/OdooPage'
import AdminPage from './pages/AdminPage'
import { API_URL } from './config/api'

export default function App() {
  const [view, setView] = useState(() => localStorage.getItem('nisab_view') || 'dashboard')
  const [backendStatus, setBackendStatus] = useState('loading')
  const [summary, setSummary] = useState(null)
  const [findings, setFindings] = useState([])
  const [auditLoading, setAuditLoading] = useState(false)
  const [hasData, setHasData] = useState(false)

  const changeView = (v) => {
    setView(v)
    localStorage.setItem('nisab_view', v)
  }

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(() => setBackendStatus('ok'))
      .catch(() => setBackendStatus('offline'))

    fetch(`${API_URL}/dashboard/summary`)
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => {
        if (s && s.status !== 'no_data' && s.company) {
          setSummary(s)
          setHasData(true)
          fetch(`${API_URL}/audit/run`, { method: 'POST' })
            .then((r) => (r.ok ? r.json() : null))
            .then((d) => {
              if (d) setFindings(d.findings || [])
            })
        }
      })
      .catch(() => {})
  }, [])

  const runAudit = useCallback(async () => {
    setAuditLoading(true)
    try {
      const [auditRes, summaryRes] = await Promise.all([
        fetch(`${API_URL}/audit/run?force=true`, { method: 'POST' }),
        fetch(`${API_URL}/dashboard/summary`),
      ])
      if (auditRes.ok) {
        const d = await auditRes.json()
        setFindings(d.findings || [])
      }
      if (summaryRes.ok) {
        const s = await summaryRes.json()
        setSummary(s)
        setHasData(s.status !== 'no_data' && Boolean(s.company))
      }
    } catch (e) {
      console.error(e)
    } finally {
      setAuditLoading(false)
    }
  }, [])

  const handleDataLoaded = useCallback(() => {
    setHasData(true)
    runAudit()
  }, [runAudit])

  return (
    <div className="shell">
      <Sidebar view={view} onChangeView={changeView} backendStatus={backendStatus} />

      <div className="main-content">
        <Topbar view={view} hasData={hasData} auditLoading={auditLoading} onRunAudit={runAudit} />

        <div className="page">
          {view === 'dashboard' && (
            <DashboardPage
              summary={summary}
              onRunAudit={runAudit}
              auditLoading={auditLoading}
              findings={findings}
              onGoToAudit={() => changeView('audit')}
            />
          )}
          {view === 'audit' && (
            <AuditPage findings={findings} onRunAudit={runAudit} loading={auditLoading} hasData={hasData} />
          )}
          {view === 'calendar' && <CalendarPage />}
          {view === 'chat' && <ChatPage />}
          {view === 'odoo' && (
            <OdooPage onConnected={handleDataLoaded} onDemoLoaded={handleDataLoaded} />
          )}
          {view === 'admin' && <AdminPage />}
        </div>
      </div>

      <GlobalCopilot activeView={view} findings={findings} />
    </div>
  )
}
