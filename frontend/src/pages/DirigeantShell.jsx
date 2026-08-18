import { useEffect, useState } from 'react'
import { ArrowLeft, Clock, LogOut, ShieldQuestion, UserCircle } from 'lucide-react'
import { apiFetch } from '../config/api'
import { useAuth } from '../context/AuthContext'
import { useDossier } from '../context/DossierContext'
import Badge from '../components/ui/Badge'
import ProfilePage from './ProfilePage'

// ── Feu tricolore : dérivé de dashboard/summary, sans rien recalculer ──
// rouge  : au moins une anomalie critique ouverte
// orange : anomalies modérées seulement
// vert   : audit exécuté, rien détecté
// gris   : pas de donnée chargée, audit jamais lancé, ou audit techniquement
//          indisponible ; affiché comme "indéterminé", JAMAIS confondu avec
//          "vert" (conforme).
//
// Le cas `jamais_lance` est le plus important des trois gris, et le plus
// récent : depuis que l'audit ne se déclenche plus tout seul, un dossier peut
// rester durablement non analysé. Sans ce test, `risks` valant {0,0,0}, le
// dirigeant verrait « Situation saine » sur un dossier que personne n'a
// jamais audité — une certification de conformité sans aucune vérification,
// affichée au seul utilisateur qui n'a pas les moyens de la contredire (le
// shell dirigeant est en lecture seule, il ne peut pas lancer d'analyse).
function feuTricolore(summary) {
  if (!summary || summary.status === 'no_data') return 'gris'
  if (summary.audit_status === 'jamais_lance' || summary.audit_status === 'error') return 'gris'
  if ((summary.risks?.rouge || 0) > 0) return 'rouge'
  if ((summary.risks?.orange || 0) > 0) return 'orange'
  return 'vert'
}

const FEU_CONFIG = {
  rouge: { label: 'Attention requise', cls: 'critique' },
  orange: { label: 'À surveiller', cls: 'vigilance' },
  vert: { label: 'Situation saine', cls: 'conforme' },
  gris: { label: 'Indéterminé', cls: 'neutral' },
}

function DossierFeuCard({ dossier }) {
  const [summary, setSummary] = useState(null)
  const [nextEcheance, setNextEcheance] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const [summaryRes, calendarRes] = await Promise.all([
          apiFetch(`/dossiers/${dossier.id}/dashboard/summary`),
          apiFetch(`/dossiers/${dossier.id}/calendar/events`),
        ])
        if (!cancelled) {
          setSummary(summaryRes.ok ? await summaryRes.json() : null)
          const cal = calendarRes.ok ? await calendarRes.json() : { events: [] }
          setNextEcheance((cal.events || [])[0] || null)
        }
      } catch (e) {
        console.error(e)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [dossier.id])

  const feu = feuTricolore(summary)
  const { label, cls } = FEU_CONFIG[feu]

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-body">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
          <div>
            <div style={{ fontFamily: 'var(--font-display)', fontSize: 15, fontWeight: 600, color: 'var(--encre)' }}>{dossier.raison_sociale}</div>
            <div style={{ fontSize: 11.5, color: 'var(--sourdine)' }}>{dossier.secteur_activite || 'Secteur non renseigné'}</div>
          </div>
          {/* Composant Badge partagé (carré + texte neutre) — un span
              `badge ${cls}` fait main sans `.badge-dot` ne colore RIEN sous
              Direction D (le sélecteur CSS cible `.badge.<cls> .badge-dot`),
              même bug que celui trouvé et corrigé sur InvitationsPage. */}
          <Badge cls={cls}>{label}</Badge>
        </div>

        {loading ? (
          <div style={{ fontSize: 12.5, color: 'var(--sourdine)' }}>Chargement…</div>
        ) : summary?.status === 'no_data' ? (
          <div style={{ fontSize: 12.5, color: 'var(--sourdine)' }}>
            Aucune donnée comptable chargée pour ce dossier — contactez votre cabinet.
          </div>
        ) : summary?.audit_status === 'jamais_lance' ? (
          <div style={{ fontSize: 12.5, color: 'var(--sourdine)' }}>
            Les données comptables sont chargées mais l'analyse fiscale n'a pas encore été réalisée — contactez votre
            cabinet pour la lancer.
          </div>
        ) : (
          <>
            <div style={{ fontSize: 13, color: 'var(--ardoise)', lineHeight: 1.55, marginBottom: 12 }}>
              {summary?.executive_summary || 'Analyse indisponible pour le moment.'}
            </div>
            {nextEcheance && (
              <div style={{
                display: 'flex', alignItems: 'center', gap: 8, fontSize: 12,
                color: 'var(--sourdine)', borderTop: '1px solid var(--bordure)', paddingTop: 10,
              }}>
                <Clock size={13} />
                Prochaine échéance : <strong style={{ color: 'var(--ardoise)' }}>{nextEcheance.title}</strong>
                {' '}— {new Date(nextEcheance.date).toLocaleDateString('fr-MA', { day: 'numeric', month: 'long', year: 'numeric' })}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default function DirigeantShell() {
  const { user, logout } = useAuth()
  const { dossiers, loading } = useDossier()
  const [view, setView] = useState('dashboard') // 'dashboard' | 'profile'

  return (
    <div style={{ minHeight: '100vh', background: 'var(--toile)' }}>
      <header style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '16px 24px', background: 'var(--surface)', borderBottom: '1px solid var(--bordure)',
      }}>
        {/* Direction D retire le pictogramme de marque partout (Sidebar.jsx
            .brand-mark { display:none }) — resté ici sous forme d'un carré
            "N" codé en dur, jamais mis à jour depuis. */}
        <div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 17, fontWeight: 600, color: 'var(--encre)', letterSpacing: '-0.01em' }}>Nisab</div>
          <div style={{ fontSize: 10.5, color: 'var(--sourdine)' }}>Espace dirigeant</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => setView(view === 'profile' ? 'dashboard' : 'profile')}
            title="Mon profil"
            style={{ fontSize: 12.5, color: 'var(--ardoise)', display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <UserCircle size={15} /> {user?.nom_complet || user?.email}
          </button>
          <button className="btn btn-secondary btn-sm" onClick={logout} title="Se déconnecter">
            <LogOut size={13} />
          </button>
        </div>
      </header>

      <main style={{ maxWidth: 680, margin: '0 auto', padding: '32px 20px' }}>
        {view === 'profile' ? (
          <>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setView('dashboard')}
              style={{ marginBottom: 16 }}
            >
              <ArrowLeft size={13} /> Retour
            </button>
            <ProfilePage />
          </>
        ) : (
          <>
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 600, color: 'var(--encre)' }}>Votre situation fiscale</div>
              <div style={{ fontSize: 13, color: 'var(--sourdine)' }}>
                Vue d'ensemble simplifiée — pour le détail, votre cabinet comptable reste votre interlocuteur.
              </div>
            </div>

            {loading ? (
              <div style={{ fontSize: 13, color: 'var(--sourdine)' }}>Chargement de vos dossiers…</div>
            ) : dossiers.length === 0 ? (
              <div className="empty-state">
                <div className="empty-state-icon"><ShieldQuestion size={22} /></div>
                <div className="empty-state-title">Aucun dossier ne vous a encore été rattaché</div>
                <div className="empty-state-sub">Contactez votre cabinet comptable pour qu'il vous donne accès à votre dossier.</div>
              </div>
            ) : (
              dossiers.map((d) => <DossierFeuCard key={d.id} dossier={d} />)
            )}
          </>
        )}
      </main>
    </div>
  )
}
