import { useCallback, useEffect, useState } from 'react'
import { BellRing, CheckCheck, RefreshCw } from 'lucide-react'
import Badge from '../components/ui/Badge'
import CitationPills from '../components/audit/CitationPills'
import { dossierFetch } from '../config/api'
import { useDossier } from '../context/DossierContext'

// Un BO porte une mesure nouvelle et datée, une consolidation du CGI reformule
// du texte déjà en vigueur : les deux n'appellent pas la même réaction, d'où
// deux traitements visuels distincts (règle d'architecture CGI ≠ BO).
const NIVEAUX = { eleve: 'critique', moyen: 'vigilance', faible: 'neutral' }

function estBO(n) {
  return /bo|bulletin/i.test(n.source_label || n.document_id || '')
}

/**
 * Veille personnalisée (Module 6).
 *
 * Ce que la page doit faire comprendre en un coup d'œil : une notification
 * n'est pas une newsletter. Elle apparaît parce que CE dossier a déjà cité
 * CET article — le champ `motif` le dit explicitement, et c'est ce qui
 * distingue « veille personnalisée » de « veille ».
 */
export default function VeillePage() {
  const { activeDossier } = useDossier()
  const [notifications, setNotifications] = useState([])
  const [nbNonLues, setNbNonLues] = useState(0)
  const [loading, setLoading] = useState(true)
  const [erreur, setErreur] = useState(null)

  const charger = useCallback(async () => {
    setLoading(true)
    setErreur(null)
    try {
      const res = await dossierFetch('/veille')
      if (!res.ok) throw new Error('Chargement des notifications impossible.')
      const d = await res.json()
      setNotifications(d.notifications || [])
      setNbNonLues(d.nb_non_lues || 0)
    } catch (e) {
      setErreur(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (activeDossier) charger()
  }, [activeDossier, charger])

  const marquerLu = async (id) => {
    try {
      await dossierFetch(`/veille/${id}`, { method: 'PATCH', body: JSON.stringify({ lu: true }) })
      setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, lu: true } : n)))
      setNbNonLues((n) => Math.max(0, n - 1))
    } catch {
      // Marquer comme lu n'est pas critique : un échec ne mérite pas d'alarme.
    }
  }

  const toutMarquerLu = async () => {
    try {
      await dossierFetch('/veille/tout-lu', { method: 'POST' })
      setNotifications((prev) => prev.map((n) => ({ ...n, lu: true })))
      setNbNonLues(0)
    } catch {
      setErreur('Impossible de tout marquer comme lu.')
    }
  }

  if (!activeDossier) return null

  return (
    <div>
      <div className="section-header" style={{ alignItems: 'center' }}>
        <div>
          <div className="section-sub">
            Évolutions du corpus portant sur des articles déjà utilisés pour ce dossier.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-secondary btn-sm" onClick={charger} disabled={loading}>
            {loading ? <span className="spinner dark" /> : <RefreshCw size={13} />} Actualiser
          </button>
          {nbNonLues > 0 && (
            <button className="btn btn-secondary btn-sm" onClick={toutMarquerLu}>
              <CheckCheck size={13} /> Tout marquer comme lu
            </button>
          )}
        </div>
      </div>

      {erreur && (
        <div className="alert critique" style={{ marginBottom: 14 }}>
          <div className="alert-dot" /><div>{erreur}</div>
        </div>
      )}

      {!loading && notifications.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon"><BellRing size={22} /></div>
          <div className="empty-state-title">Aucune évolution signalée</div>
          <div className="empty-state-sub">
            Les notifications apparaissent quand un article déjà cité sur ce dossier
            — par une alerte, l'assistant, une simulation ou une correction — évolue dans le corpus.
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {notifications.map((n) => (
            <div key={n.id} className="card" style={{ opacity: n.lu ? 0.72 : 1 }}>
              <div className="card-body">
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginBottom: 8 }}>
                  <Badge cls={NIVEAUX[n.niveau] || 'neutral'}>
                    {estBO(n) ? 'Bulletin Officiel' : 'CGI'}
                  </Badge>
                  {!n.lu && <Badge cls="seuil">Non lue</Badge>}
                  <div style={{ flex: 1 }} />
                  <span className="mono" style={{ fontSize: 11, color: 'var(--sourdine)' }}>
                    {n.created_at?.slice(0, 10)}
                  </span>
                </div>

                <div style={{ fontSize: 13, fontWeight: n.lu ? 400 : 600, color: 'var(--encre)', lineHeight: 1.55, marginBottom: 8 }}>
                  {n.message}
                </div>

                {/* Le motif est ce qui rend la veille « personnalisée » : il dit
                    pourquoi CE dossier reçoit CETTE notification. */}
                {n.motif && (
                  <div style={{ fontSize: 12, color: 'var(--ardoise)', marginBottom: 10 }}>
                    <strong>Pourquoi ce dossier :</strong> {n.motif.toLowerCase()}
                  </div>
                )}

                <CitationPills principale={n.reference} titre="Article concerné — cliquez pour lire le texte" />

                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4 }}>
                  {n.source_label && (
                    <span style={{ fontSize: 11, color: 'var(--sourdine)' }}>
                      Source : {n.source_label}{n.date_version ? ` — ${n.date_version}` : ''}
                    </span>
                  )}
                  <div style={{ flex: 1 }} />
                  {!n.lu && (
                    <button className="btn btn-ghost btn-sm" onClick={() => marquerLu(n.id)}>
                      Marquer comme lue
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
