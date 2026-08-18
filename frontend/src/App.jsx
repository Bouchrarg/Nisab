import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import GlobalCopilot from './GlobalCopilot'
import Sidebar from './components/layout/Sidebar'
import Topbar from './components/layout/Topbar'
import CabinetOverviewPage from './pages/CabinetOverviewPage'
import DashboardPage from './pages/DashboardPage'
import AuditPage from './pages/AuditPage'
import CorrectionsPage from './pages/CorrectionsPage'
import VeillePage from './pages/VeillePage'
import SimulationPage from './pages/SimulationPage'
import CalendarPage from './pages/CalendarPage'
import ChatPage from './pages/ChatPage'
import OdooPage from './pages/OdooPage'
import LoginPage from './pages/LoginPage'
import PlatformAdminShell from './pages/PlatformAdminShell'
import DirigeantShell from './pages/DirigeantShell'
import ProfilePage from './pages/ProfilePage'
import InvitationsPage from './pages/InvitationsPage'
import AcceptInvitePage from './pages/AcceptInvitePage'
import { API_URL, apiFetch, dossierFetch } from './config/api'
import { useAuth } from './context/AuthContext'
import { useDossier } from './context/DossierContext'

// Vues qui ont besoin d'un dossier actif pour avoir un sens.
const DOSSIER_SCOPED_VIEWS = new Set(['dashboard', 'audit', 'corrections', 'simulation', 'calendar', 'veille'])
// 'chat' exclu volontairement : cette vue EST déjà un assistant plein écran
// (ChatPage) — le copilote flottant par-dessus affichait deux chats en même
// temps sur le même écran.
const COPILOT_VIEWS = new Set(['dashboard', 'audit', 'corrections', 'simulation', 'calendar', 'odoo', 'veille'])

// L'audit reste synchrone côté backend (2 appels LLM séquentiels par
// écriture, plus retries/fallback OpenRouter en cas de rate limit) : pour
// un dossier avec plusieurs dizaines d'écritures, l'attente réelle peut
// dépasser 5 min en conditions réelles (constaté). Ce timeout n'est qu'un
// garde-fou UI contre un blocage vraiment anormal (réseau coupé, backend
// planté) — le backend, lui, n'a aucune notion d'annulation et continue de
// tourner et d'enregistrer son résultat même si le client abandonne.
const AUDIT_TIMEOUT_MS = 15 * 60 * 1000

// Construit la query string de /audit/run à partir des options actives.
// `documentId` vide = comportement historique (corpus valide entier, sans
// distinction de millésime) ; fourni, contraint le RAG à ce document précis
// (voir GET /corpus/sources pour les valeurs possibles).
function buildAuditQuery({ force = false, documentId = '' } = {}) {
  const params = new URLSearchParams()
  if (force) params.set('force', 'true')
  if (documentId) params.set('document_id', documentId)
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

async function fetchAuditRun(query = '') {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), AUDIT_TIMEOUT_MS)
  try {
    const res = await dossierFetch(`/audit/run${query}`, { method: 'POST', signal: controller.signal })
    if (!res.ok) {
      const errBody = await res.json().catch(() => null)
      throw new Error(errBody?.detail || `L'audit a échoué (code ${res.status}).`)
    }
    return await res.json()
  } catch (e) {
    if (e.name === 'AbortError') {
      throw new Error(
        "L'analyse a dépassé 15 min côté navigateur et l'attente a été interrompue ici, mais le calcul continue "
        + 'côté serveur et son résultat sera enregistré normalement — rechargez cette page dans quelques minutes '
        + 'pour le voir.'
      )
    }
    throw e
  } finally {
    clearTimeout(timeoutId)
  }
}

function AppShell() {
  const [view, setView] = useState(() => localStorage.getItem('nisab_view') || 'overview')
  const [backendStatus, setBackendStatus] = useState('loading')
  // Alertes critiques cabinet — calculées par CabinetOverviewPage (seule à
  // charger le résumé de chaque dossier) et remontées ici pour que la
  // cloche de notifications, elle, vive dans le Topbar (persistant, visible
  // quelle que soit la vue), pas enterrée dans le contenu d'une page.
  const [criticalAlerts, setCriticalAlerts] = useState([])
  const [summary, setSummary] = useState(null)
  const [findings, setFindings] = useState([])
  // Propositions de correction, indexees par alerte_id : FindingCard doit
  // savoir si l'anomalie qu'il affiche a deja une proposition, sans refaire
  // un appel par carte.
  const [propositions, setPropositions] = useState({})
  const [propositionEnCours, setPropositionEnCours] = useState(null)
  const [technicalFailures, setTechnicalFailures] = useState([])
  const [inconclusive, setInconclusive] = useState([])
  const [auditError, setAuditError] = useState(null)
  const [auditLoading, setAuditLoading] = useState(false)
  // 'jamais_lance' | 'done'. Distingue « ce dossier n'a jamais été analysé »
  // de « analysé, aucune anomalie » — deux situations qui donnent toutes deux
  // une liste de findings vide, et que l'écran affichait jusqu'ici de la même
  // façon : un bandeau vert « bonne conformité » sur un dossier que personne
  // n'avait jamais audité.
  const [auditStatus, setAuditStatus] = useState('jamais_lance')
  const [auditDate, setAuditDate] = useState(null)
  // true = le résultat affiché n'a pas été produit à partir du couple
  // (données comptables, millésime de corpus) actuellement sélectionné.
  // Remplace le re-lancement automatique : on le SIGNALE au lieu de partir
  // dans plusieurs minutes de calcul sans prévenir.
  const [resultatPerime, setResultatPerime] = useState(false)
  const [hasData, setHasData] = useState(false)
  const [simulation, setSimulation] = useState(null)
  const [simulationLoading, setSimulationLoading] = useState(false)
  const [simulationHistory, setSimulationHistory] = useState([])
  // Source de corpus choisie pour l'audit ('' = toutes les sources valides,
  // comportement historique). document_id d'un document du corpus (ex:
  // "cgi_2024"), pas scopé par dossier : le choix reste actif si on change
  // de dossier, comme le reste des filtres UI de ce shell.
  const [sourceAudit, setSourceAudit] = useState('')
  const [corpusSources, setCorpusSources] = useState([])

  const { user } = useAuth()
  const { activeDossier, setActiveDossier } = useDossier()

  // Garde contre les réponses obsolètes : l'audit peut prendre plusieurs
  // minutes. Si l'utilisateur change de dossier pendant qu'une requête est
  // encore en vol pour l'ANCIEN dossier, sa réponse ne doit pas écraser
  // l'état du NOUVEAU dossier affiché entre-temps (sinon : on change de
  // dossier et on voit encore l'analyse du précédent).
  const activeDossierIdRef = useRef(activeDossier?.id ?? null)
  useEffect(() => {
    activeDossierIdRef.current = activeDossier?.id ?? null
  }, [activeDossier])

  const changeView = (v) => {
    setView(v)
    localStorage.setItem('nisab_view', v)
  }

  const openDossier = useCallback((dossier) => {
    // Le dossier passé par CabinetOverviewPage (clic sur une carte ou une
    // alerte critique) était jusqu'ici silencieusement ignoré : on changeait
    // de vue sans jamais activer ce dossier, donc le Tableau de bord
    // continuait d'afficher l'ancien dossier actif.
    if (dossier) setActiveDossier(dossier)
    changeView('dashboard')
  }, [setActiveDossier])

  // LECTURE SEULE — ne lance jamais d'audit.
  //
  // Cette fonction appelait `fetchAuditRun` (POST /audit/run) au montage de
  // l'app, à chaque changement de dossier ET à chaque changement de millésime
  // dans le <select> de la page Audit. Un audit dure plusieurs minutes : le
  // produit partait donc en calcul sans que personne ne l'ait demandé, et
  // `auditLoading` n'étant même pas positionné sur ce chemin, rien à l'écran
  // ne l'indiquait. Elle lit désormais GET /audit/resultat, qui sert le dernier
  // audit enregistré sans rappeler le LLM. Relancer une analyse est le rôle de
  // `runAudit`, appelé uniquement sur clic.
  const loadDashboard = useCallback(async () => {
    if (!activeDossier) return
    const dossierIdAtCall = activeDossier.id
    const isStale = () => activeDossierIdRef.current !== dossierIdAtCall
    setAuditError(null)
    try {
      const summaryRes = await dossierFetch('/dashboard/summary')
      if (isStale()) return
      const s = summaryRes.ok ? await summaryRes.json() : null
      if (isStale()) return
      if (s && s.status !== 'no_data' && s.company) {
        setSummary(s)
        setHasData(true)
        const res = await dossierFetch(`/audit/resultat${buildAuditQuery({ documentId: sourceAudit })}`)
        if (isStale() || !res.ok) return
        const d = await res.json()
        if (isStale()) return
        setFindings(d.findings || [])
        setAuditStatus(d.audit_status || 'jamais_lance')
        setAuditDate(d.date_dernier_audit || null)
        setResultatPerime(Boolean(d.resultat_perime))
        // Ni technical_failures ni inconclusive ne sont persistés en base :
        // ils décrivent le DÉROULÉ d'un run (une écriture que le LLM n'a pas
        // su trancher), pas son résultat. Les vider ici est volontaire — les
        // afficher à côté d'un audit relu ferait croire que l'analyse vient
        // de tourner.
        setTechnicalFailures([])
        setInconclusive([])
      } else {
        setSummary(null)
        setHasData(false)
        setFindings([])
        setAuditStatus('jamais_lance')
        setAuditDate(null)
        setResultatPerime(false)
        setTechnicalFailures([])
        setInconclusive([])
      }
    } catch (e) {
      if (isStale()) return
      setAuditError(e.message || "Erreur lors du chargement du tableau de bord.")
      console.error(e)
    }
  }, [activeDossier, sourceAudit])

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(() => setBackendStatus('ok'))
      .catch(() => setBackendStatus('offline'))
  }, [])

  // Corpus partagé, pas scopé par dossier : chargé une fois pour peupler le
  // sélecteur de source de l'audit.
  useEffect(() => {
    apiFetch('/corpus/sources')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setCorpusSources(d?.sources || []))
      .catch(() => setCorpusSources([]))
  }, [])

  const loadPropositions = useCallback(async () => {
    if (!activeDossier) return
    const dossierIdAtCall = activeDossier.id
    const isStale = () => activeDossierIdRef.current !== dossierIdAtCall
    try {
      const res = await dossierFetch('/propositions')
      if (isStale() || !res.ok) return
      const d = await res.json()
      if (isStale()) return
      // Indexation par alerte_id : une seule proposition vivante par alerte
      // est garantie par un index unique cote base (ux_proposition_vivante),
      // donc ecraser sans precaution est correct ici.
      const parAlerte = {}
      for (const p of d.propositions || []) {
        if (p.statut !== 'rejetee' || !parAlerte[p.alerte_id]) parAlerte[p.alerte_id] = p
      }
      setPropositions(parAlerte)
    } catch {
      // Non bloquant : l'audit reste consultable sans les propositions.
    }
  }, [activeDossier])

  useEffect(() => {
    loadDashboard()
  }, [loadDashboard])

  useEffect(() => {
    loadPropositions()
  }, [loadPropositions])

  const proposerCorrection = useCallback(async (finding) => {
    if (!activeDossier || !finding?.id) return
    setPropositionEnCours(finding.id)
    setAuditError(null)
    try {
      const res = await dossierFetch(`/alertes/${finding.id}/proposition`, { method: 'POST' })
      if (!res.ok) {
        const body = await res.json().catch(() => null)
        throw new Error(body?.detail || 'La generation de la correction a echoue.')
      }
      const p = await res.json()
      setPropositions((prev) => ({ ...prev, [p.alerte_id]: p }))
      changeView('corrections')
    } catch (e) {
      setAuditError(e.message)
    } finally {
      setPropositionEnCours(null)
    }
  }, [activeDossier])

  // Confirmation comptable du statut Art. 151 (retenue à la source) — seul
  // moyen de sortir cette anomalie de "non_calculable" (voir
  // regles_montant.remuneration_tiers_non_declaree_art151 côté backend :
  // le statut fiscal du bénéficiaire n'est dérivable d'aucune donnée
  // comptable). Met à jour le finding en place plutôt que de relancer tout
  // l'audit — la réponse du backend contient déjà le montant recalculé.
  const confirmerRetenueSource = useCallback(async (finding, { applicable, montantDu }) => {
    if (!activeDossier || !finding?.id) return
    const res = await dossierFetch(`/alertes/${finding.id}/retenue-source`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ applicable, montant_du: applicable ? montantDu : null }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => null)
      throw new Error(body?.detail || 'La confirmation a échoué.')
    }
    const updated = await res.json()
    setFindings((prev) => prev.map((f) => (f.id === updated.id ? updated : f)))
  }, [activeDossier])

  const runAudit = useCallback(async () => {
    if (!activeDossier) return
    const dossierIdAtCall = activeDossier.id
    const isStale = () => activeDossierIdRef.current !== dossierIdAtCall
    setAuditLoading(true)
    setAuditError(null)
    // On vide le résultat précédent tout de suite : sinon il reste affiché,
    // inchangé, pendant les (potentiellement plusieurs minutes) que prend
    // le nouveau calcul, ce qui donne l'impression que rien ne se passe.
    setFindings([])
    setTechnicalFailures([])
    setInconclusive([])
    try {
      // Séquentiel, pas Promise.all. Les deux requêtes partaient en parallèle
      // alors que /dashboard/summary lançait lui aussi un audit : elles se
      // disputaient le verrou serveur `_lock_for(dossier_id)`, et comme le
      // résumé appelait sans `document_id`, son hash de cache ne pouvait pas
      // correspondre — un SECOND audit complet repartait donc juste après le
      // premier. Le résumé est désormais une simple lecture, il doit
      // simplement passer APRÈS pour refléter le run qu'on vient de faire.
      const d = await fetchAuditRun(buildAuditQuery({ force: true, documentId: sourceAudit }))
      if (isStale()) return
      setFindings(d.findings || [])
      setTechnicalFailures(d.technical_failures || [])
      setInconclusive(d.inconclusive || [])
      setAuditStatus('done')
      setAuditDate(new Date().toISOString())
      setResultatPerime(false)

      const summaryRes = await dossierFetch('/dashboard/summary')
      if (isStale()) return
      if (summaryRes.ok) {
        const s = await summaryRes.json()
        if (isStale()) return
        setSummary(s)
        setHasData(s.status !== 'no_data' && Boolean(s.company))
      }
    } catch (e) {
      if (isStale()) return
      setAuditError(e.message || "Erreur lors du lancement de l'audit.")
      console.error(e)
    } finally {
      if (!isStale()) setAuditLoading(false)
    }
  }, [activeDossier, sourceAudit])

  const loadLatestSimulation = useCallback(async () => {
    if (!activeDossier) return
    const dossierIdAtCall = activeDossier.id
    const isStale = () => activeDossierIdRef.current !== dossierIdAtCall
    try {
      const res = await dossierFetch('/simulations')
      if (isStale() || !res.ok) return
      const d = await res.json()
      if (isStale()) return
      const list = d.simulations || []
      setSimulationHistory(list)
      const latest = list[0]
      if (!latest) {
        setSimulation(null)
        return
      }
      const detailRes = await apiFetch(`/simulations/${latest.id}`)
      if (isStale()) return
      if (detailRes.ok) setSimulation(await detailRes.json())
    } catch (e) {
      console.error(e)
    }
  }, [activeDossier])

  const runSimulation = useCallback(async () => {
    if (!activeDossier) return
    const dossierIdAtCall = activeDossier.id
    const isStale = () => activeDossierIdRef.current !== dossierIdAtCall
    setSimulationLoading(true)
    try {
      const res = await dossierFetch('/simulation/run', { method: 'POST' })
      if (isStale()) return
      if (res.ok) {
        setSimulation(await res.json())
        loadLatestSimulation()
      }
    } catch (e) {
      console.error(e)
    } finally {
      if (!isStale()) setSimulationLoading(false)
    }
  }, [activeDossier, loadLatestSimulation])

  const viewSimulation = useCallback(async (simulationId) => {
    try {
      const res = await apiFetch(`/simulations/${simulationId}`)
      if (res.ok) setSimulation(await res.json())
    } catch (e) {
      console.error(e)
    }
  }, [])

  const exportSimulationPdf = useCallback(async (simulationId) => {
    const id = simulationId || simulation?.id
    if (!id) return
    try {
      const res = await apiFetch(`/simulations/${id}/export`)
      if (!res.ok) return
      const disposition = res.headers.get('content-disposition') || ''
      const match = disposition.match(/filename="([^"]+)"/)
      const filename = match ? match[1] : `simulation_${id}.pdf`
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      console.error(e)
    }
  }, [simulation])

  useEffect(() => {
    setSimulation(null)
    setSimulationHistory([])
    loadLatestSimulation()
  }, [loadLatestSimulation])

  // Charger des données comptables (Odoo, démo, import CSV/Excel) ne lance
  // PLUS l'audit. Se connecter à Odoo pour regarder ce qui a été importé
  // déclenchait plusieurs minutes de LLM, alors même que le bandeau de
  // succès d'OdooPage dit « Rendez-vous dans Audit pour lancer l'analyse ».
  // On marque le résultat affiché comme périmé et on laisse l'utilisateur
  // décider quand analyser.
  const handleDataLoaded = useCallback(() => {
    setHasData(true)
    setResultatPerime(true)
    loadDashboard()
  }, [loadDashboard])

  const needsDossierButMissing = DOSSIER_SCOPED_VIEWS.has(view) && !activeDossier

  return (
    <div className="shell">
      <Sidebar view={view} onChangeView={changeView} backendStatus={backendStatus} role={user?.role} />

      <div className="main-content">
        <Topbar
          view={view}
          onOpenProfile={() => changeView('profile')}
          criticalAlerts={criticalAlerts}
          onOpenDossier={openDossier}
        />

        <div className="page">
          {view === 'overview' && (
            <CabinetOverviewPage onOpenDossier={openDossier} onCriticalAlertsChange={setCriticalAlerts} />
          )}
          {view === 'profile' && <ProfilePage />}
          {view === 'invitations' && user?.role === 'admin_cabinet' && <InvitationsPage />}

          {needsDossierButMissing ? (
            <div className="no-dossier-inline">
              <p>Sélectionnez ou créez d'abord un dossier.</p>
              <button className="btn btn-primary btn-sm" onClick={() => changeView('overview')}>
                Aller à la vue d'ensemble
              </button>
            </div>
          ) : (
            <>
              {view === 'dashboard' && (
                <DashboardPage
                  summary={summary}
                  onRunAudit={runAudit}
                  auditLoading={auditLoading}
                  findings={findings}
                  auditStatus={auditStatus}
                  auditDate={auditDate}
                  resultatPerime={resultatPerime}
                  onGoToAudit={() => changeView('audit')}
                  onGoToCalendar={() => changeView('calendar')}
                />
              )}
              {view === 'audit' && (
                <AuditPage
                  findings={findings}
                  technicalFailures={technicalFailures}
                  inconclusive={inconclusive}
                  error={auditError}
                  onRunAudit={runAudit}
                  loading={auditLoading}
                  hasData={hasData}
                  auditStatus={auditStatus}
                  auditDate={auditDate}
                  resultatPerime={resultatPerime}
                  propositions={propositions}
                  onProposer={proposerCorrection}
                  onVoirProposition={() => changeView('corrections')}
                  propositionEnCours={propositionEnCours}
                  corpusSources={corpusSources}
                  sourceAudit={sourceAudit}
                  onChangeSourceAudit={setSourceAudit}
                  onConfirmerRetenueSource={confirmerRetenueSource}
                />
              )}
              {view === 'corrections' && <CorrectionsPage />}
              {view === 'veille' && <VeillePage />}
              {view === 'simulation' && (
                <SimulationPage
                  simulation={simulation}
                  history={simulationHistory}
                  onRunSimulation={runSimulation}
                  onExportPdf={exportSimulationPdf}
                  onViewSimulation={viewSimulation}
                  loading={simulationLoading}
                  hasData={hasData}
                />
              )}
              {view === 'calendar' && <CalendarPage />}
              {view === 'chat' && <ChatPage dossierId={activeDossier?.id} />}
              {view === 'odoo' && (
                <OdooPage onConnected={handleDataLoaded} onDemoLoaded={handleDataLoaded} />
              )}
            </>
          )}
        </div>
      </div>

      {COPILOT_VIEWS.has(view) && <GlobalCopilot activeView={view} findings={findings} dossierId={activeDossier?.id} />}
    </div>
  )
}

export default function App() {
  const { status, user } = useAuth()

  // Lien d'invitation (?token=...) : consultable sans être connecté, avant
  // même l'écran de login classique.
  const inviteToken = new URLSearchParams(window.location.search).get('token')
  if (status !== 'authenticated' && inviteToken) {
    return (
      <AcceptInvitePage
        token={inviteToken}
        onAccepted={() => {
          window.location.href = window.location.pathname
        }}
      />
    )
  }

  if (status === 'loading') {
    return (
      <div className="auth-shell">
        <span className="spinner dark" />
      </div>
    )
  }

  if (status === 'anonymous') {
    return <LoginPage />
  }

  if (user?.role === 'admin_plateforme') {
    return <PlatformAdminShell />
  }

  if (user?.role === 'dirigeant_pme') {
    return <DirigeantShell />
  }

  return <AppShell />
}
