import { useEffect, useState } from 'react'
import { Info } from 'lucide-react'
import CalendarEvent from '../components/calendar/CalendarEvent'
import ReconciliationBanner from '../components/calendar/ReconciliationBanner'
import { dossierFetch } from '../config/api'
import { useDossier } from '../context/DossierContext'

// NOTE (Phase 3) : le régime IS/TVA est désormais une propriété du dossier
// (regime_is / regime_tva, définie à la création — voir DossierSwitcher /
// future page d'édition de dossier) plutôt qu'un choix ad hoc dans cette
// page. Le backend lit ces valeurs sur le dossier actif ; les boutons de
// bascule ont donc été retirés d'ici.
export default function CalendarPage() {
  const [events, setEvents] = useState([])
  const [reconciliation, setReconciliation] = useState(null)
  const [loading, setLoading] = useState(true)
  const [filtre, setFiltre] = useState('toutes')
  const { activeDossier } = useDossier()

  useEffect(() => {
    if (!activeDossier) return
    setLoading(true)
    setReconciliation(null)
    setFiltre('toutes')
    dossierFetch('/calendar/events')
      .then((r) => r.json())
      .then((d) => {
        setEvents(d.events || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))

    // Requête séparée et non bloquante : le calendrier (ce qui reste à faire)
    // et la réconciliation (ce qui aurait dû être fait) répondent à deux
    // questions différentes, et un échec de la seconde ne doit pas priver le
    // cabinet de la première.
    fetchReconciliation()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeDossier])

  function fetchReconciliation() {
    return dossierFetch('/reconciliation/declaratif')
      .then((r) => (r.ok ? r.json() : null))
      .then(setReconciliation)
      .catch(() => setReconciliation(null))
  }

  // Passé au bandeau : marque une échéance comme déposée à la main, puis
  // recharge la réconciliation pour que la ligne quitte le tableau rouge.
  // POST plutôt qu'un état local optimiste : la source de vérité reste le
  // backend (upsert sur dossier_id + type_declaration + periode), pas l'UI.
  async function declarerEcheance(manquante) {
    const res = await dossierFetch('/reconciliation/declarations', {
      method: 'POST',
      body: JSON.stringify({
        type_declaration: manquante.categorie,
        periode: manquante.periode,
      }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Erreur lors de la déclaration.')
    }
    await fetchReconciliation()
  }

  // Purement d'affichage, recalculé depuis `events` (déjà chargé pour la
  // liste) — pas de requête séparée pour ces compteurs.
  const now = new Date()
  const dans7Jours = new Date(now)
  dans7Jours.setDate(now.getDate() + 7)
  const dans30Jours = new Date(now)
  dans30Jours.setDate(now.getDate() + 30)
  const sous7j = events.filter((e) => {
    const d = new Date(e.date)
    return d >= now && d <= dans7Jours
  }).length
  // Rolling 30 jours, pas "le mois calendaire en cours" : mi-août, la
  // prochaine échéance est en septembre et le mois calendaire actuel
  // affichait 0 alors que la liste juste en dessous n'était pas vide —
  // lu comme un bug plutôt que comme "rien avant fin août".
  const sous30j = events.filter((e) => {
    const d = new Date(e.date)
    return d >= now && d <= dans30Jours
  }).length

  // Chips de filtre par catégorie d'impôt — mêmes compteurs que la liste,
  // juste cliquables (même principe que les filtres de sévérité de
  // l'Audit). Catégories dans l'ordre où elles apparaissent, pas triées :
  // aucune n'est "plus importante" qu'une autre ici.
  const categories = []
  const byCategorie = {}
  events.forEach((e) => {
    const cat = e.category || 'Autre'
    if (!(cat in byCategorie)) { categories.push(cat); byCategorie[cat] = 0 }
    byCategorie[cat]++
  })
  const eventsAffiches = filtre === 'toutes' ? events : events.filter((e) => (e.category || 'Autre') === filtre)

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-sub">
            Échéances calculées d'après le CGI marocain, selon le régime IS/TVA du dossier « {activeDossier?.raison_sociale} ».
          </div>
        </div>
      </div>

      <div className="alert info" style={{ marginBottom: 16 }}>
        <Info size={14} style={{ flexShrink: 0 }} />
        <div style={{ fontSize: 12 }}>
          Les échéances sont calculées automatiquement à partir de la date du jour et du régime du dossier.
          Contrairement à l'audit et à l'assistant fiscal, les références légales affichées ici sont indicatives
          et n'ont pas été vérifiées contre le corpus fiscal — à confirmer auprès d'un expert avant toute décision.
        </div>
      </div>

      {/* Deux notions distinctes, souvent confondues au premier coup d'œil
          car les deux se présentent en liste de lignes datées : ce qui est
          déjà échu SANS trace de dépôt (passé, ReconciliationBanner) contre
          ce qui reste à faire (futur, la liste plus bas). Un intitulé
          au-dessus de chaque bloc, pas juste la couleur du bandeau, pour
          que la distinction tienne même en lecture rapide. */}
      {reconciliation?.echeances_manquantes?.length > 0 && (
        <div className="calendar-section-label">Échues, sans déclaration</div>
      )}
      <ReconciliationBanner data={reconciliation} onDeclarer={declarerEcheance} />

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
          <span className="spinner dark" style={{ width: 22, height: 22 }} />
        </div>
      ) : (
        <>
          {events.length > 0 && (
            <>
              <div className="calendar-section-label">À venir</div>
              <div className="calendar-kpi-row">
                <div className={`calendar-kpi${sous7j > 0 ? ' is-urgent' : ''}`}>
                  <div className="calendar-kpi-label">Échéances sous 7 jours</div>
                  <div className="calendar-kpi-value">{sous7j}</div>
                </div>
                <div className="calendar-kpi">
                  <div className="calendar-kpi-label">Échéances sous 30 jours</div>
                  <div className="calendar-kpi-value">{sous30j}</div>
                </div>
              </div>
            </>
          )}

          {events.length === 0 ? (
            <div className="alert neutral">
              <div className="alert-dot" />Aucune échéance dans les 6 prochains mois.
            </div>
          ) : (
            <>
              {categories.length > 1 && (
                <div className="filter-row">
                  <button
                    className={`filter-chip${filtre === 'toutes' ? ' is-active' : ''}`}
                    onClick={() => setFiltre('toutes')}
                  >
                    Toutes ({events.length})
                  </button>
                  {categories.map((cat) => (
                    <button
                      key={cat}
                      className={`filter-chip${filtre === cat ? ' is-active' : ''}`}
                      onClick={() => setFiltre(cat)}
                    >
                      {cat} ({byCategorie[cat]})
                    </button>
                  ))}
                </div>
              )}

              <div className="calendar-list">
                <div className="calendar-list-head">
                  <span className="calendar-list-head-date">Date</span>
                  <span className="calendar-list-head-title">Échéance</span>
                  <span className="calendar-list-head-tag">Impôt</span>
                </div>
                {eventsAffiches.map((e, i) => <CalendarEvent key={i} e={e} />)}
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
