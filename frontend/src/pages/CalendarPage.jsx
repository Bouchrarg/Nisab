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
  const { activeDossier } = useDossier()

  useEffect(() => {
    if (!activeDossier) return
    setLoading(true)
    setReconciliation(null)
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

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-title">Calendrier fiscal</div>
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

      <ReconciliationBanner data={reconciliation} onDeclarer={declarerEcheance} />

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
          <span className="spinner dark" style={{ width: 22, height: 22 }} />
        </div>
      ) : (
        <div className="calendar-list">
          {events.length === 0 ? (
            <div className="alert neutral">
              <div className="alert-dot" />Aucune échéance dans les 6 prochains mois.
            </div>
          ) : (
            events.map((e, i) => <CalendarEvent key={i} e={e} />)
          )}
        </div>
      )}
    </div>
  )
}
