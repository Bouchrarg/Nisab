import { parseDate } from '../../utils/dates'

// Une ligne = date + intitulé (+ référence légale si connue) + catégorie
// d'impôt. Les anciens badges empilés (statut de paiement, urgence ET
// catégorie en double, bandeau de couleur latéral, pénalité, version du
// document) noyaient chaque échéance sous 5-6 étiquettes — le statut de
// paiement/dépôt reste visible via ReconciliationBanner, pas répété ici.
export default function CalendarEvent({ e }) {
  const dt = parseDate(e.date)
  const urgent = e.urgency === 'critique' || e.urgency === 'urgent'

  return (
    <div className="list-row">
      {dt && (
        <div className={`list-date${urgent ? ' is-urgent' : ''}`}>
          <div className="list-date-day">{dt.day}</div>
          <div className="list-date-month">{dt.month}</div>
        </div>
      )}
      <div className="list-body">
        <div className="list-title">
          {e.title}
          {/* tax_calendar.py / reconciliation.py sont volontairement non-RAG
              (sourced: false) : jamais la texture "sourcé" (coche, bordure
              pleine) des vraies citations RAG de l'audit/du chat — le
              bandeau d'info en haut de page explique déjà pourquoi une
              seule fois, pas la peine de répéter "(non vérifié)" sur
              chaque ligne. */}
          {/* .citation-pill (padding 5px 10px, même gabarit qu'un bouton
              cliquable dans CitationPills) rivalisait avec le titre dans une
              ligne de tableau compacte — .calendar-ref-tag reprend la même
              texture honnête (pointillé + italique) en beaucoup plus petit,
              au même gabarit que .citation-source-tag / .critique-tag. */}
          {e.legal_article && (
            <span className="calendar-ref-tag" style={{ marginLeft: 8 }}>
              {e.legal_article}
            </span>
          )}
        </div>
        {e.description && <div className="list-sub">{e.description}</div>}
      </div>
      {e.category && <span className="citation-source-tag">{e.category}</span>}
    </div>
  )
}
