import { useState } from 'react'
import { ChevronDown, ChevronRight, FileWarning } from 'lucide-react'
import { parseDate } from '../../utils/dates'

/**
 * Obligations déclaratives échues sans trace de dépôt ni de paiement
 * (Module 1 — « réconciliation, détection des pièces manquantes »).
 *
 * Deux précautions de vocabulaire, volontaires et à ne pas assouplir :
 *
 *  - « aucune trace de » et jamais « vous n'avez pas déclaré ». La détection
 *    repose sur des mots-clés dans les écritures ; une déclaration déposée
 *    hors comptabilité ne laisse aucune trace exploitable. Nisab signale,
 *    le comptable tranche.
 *  - la mention non-RAG est répétée ici. Ces références légales viennent de
 *    tax_calendar.py (littéraux écrits à la main, `sourced: false`), pas du
 *    corpus versionné : elles ne doivent pas être présentées comme une
 *    citation vérifiée, contrairement à celles de l'audit ou de l'assistant.
 *
 * Détail déplié : même gabarit .list-row/.list-date que la liste principale
 * de CalendarPage, pas un <table> à part avec ses propres styles inline —
 * ouvrir ce bandeau ne doit pas faire sauter vers un autre langage visuel.
 *
 * `onDeclarer` (optionnel) : appelé avec la ligne manquante quand le cabinet
 * clique « Marquer comme déclaré ». Le composant ne connaît pas l'API — c'est
 * CalendarPage qui fait le POST et recharge la réconciliation — ce composant
 * gère juste l'état de chargement/erreur local le temps de l'appel.
 */
export default function ReconciliationBanner({ data, onDeclarer }) {
  const [ouvert, setOuvert] = useState(false)
  const [enCours, setEnCours] = useState(null) // clé de la ligne en cours de déclaration
  const [erreur, setErreur] = useState(null)
  // La fenêtre de rapprochement est glissante sur 12 mois (reconciliation.py)
  // mais chevauche fréquemment deux années civiles — utile de filtrer.
  const [anneeFiltre, setAnneeFiltre] = useState('toutes')
  if (!data) return null

  const manquantes = data.echeances_manquantes || []

  async function handleDeclarer(m, cle) {
    if (!onDeclarer) return
    setErreur(null)
    setEnCours(cle)
    try {
      await onDeclarer(m)
    } catch (e) {
      setErreur(e.message || 'Erreur lors de la déclaration.')
    } finally {
      setEnCours(null)
    }
  }

  if (manquantes.length === 0) {
    if (!data.a_des_donnees_comptables) return null
    return (
      <div className="alert conforme" style={{ marginBottom: 16 }}>
        <div className="alert-dot" />
        <div style={{ fontSize: 12.5 }}>
          Aucune obligation échue sans trace sur les {data.fenetre_mois} derniers mois
          ({data.nb_couvertes} échéance(s) rapprochée(s)).
        </div>
      </div>
    )
  }

  const categories = Object.entries(data.par_categorie || {}).sort((a, b) => b[1] - a[1])

  const annees = [...new Set(manquantes.map((m) => new Date(m.date_echeance).getFullYear()))].sort()
  const manquantesAffichees = anneeFiltre === 'toutes'
    ? manquantes
    : manquantes.filter((m) => new Date(m.date_echeance).getFullYear() === anneeFiltre)

  // Le rouge reste confiné à ce bandeau (déjà l'exception à la couleur en
  // petites touches partout ailleurs) — mais SEULEMENT sur la ligne
  // résumé, pas sur tout le détail déplié. Un empilement de 40 lignes
  // toutes teintées rose + boîte de date grise dessus donnait un gris/rouge
  // sale sur une grande surface — le détail reprend le fond neutre de la
  // liste principale (même .calendar-list), le rouge n'a plus besoin d'être
  // répété ligne par ligne : la présence dans CETTE liste dit déjà "en retard".
  return (
    <div style={{ marginBottom: 16 }}>
      <div
        className="alert critique"
        style={{ cursor: 'pointer' }}
        onClick={() => setOuvert((o) => !o)}
      >
        <FileWarning size={14} style={{ flexShrink: 0, marginTop: 2 }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <strong>{manquantes.length} obligation(s) échue(s) sans trace de dépôt ni de paiement</strong>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 6 }}>
            {categories.map(([nom, n]) => (
              <span key={nom} className="critique-tag">{nom} ({n})</span>
            ))}
          </div>
        </div>
        {ouvert ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
      </div>

      {ouvert && (
        <>
          {annees.length > 1 && (
            <div className="filter-row" style={{ margin: '12px 0 10px' }}>
              <button
                className={`filter-chip${anneeFiltre === 'toutes' ? ' is-active' : ''}`}
                onClick={() => setAnneeFiltre('toutes')}
              >
                Toutes ({manquantes.length})
              </button>
              {annees.map((an) => (
                <button
                  key={an}
                  className={`filter-chip${anneeFiltre === an ? ' is-active' : ''}`}
                  onClick={() => setAnneeFiltre(an)}
                >
                  {an} ({manquantes.filter((m) => new Date(m.date_echeance).getFullYear() === an).length})
                </button>
              ))}
            </div>
          )}
          <div className="calendar-list" style={{ borderTop: annees.length > 1 ? undefined : 'none' }}>
            {manquantesAffichees.map((m, i) => {
              const cle = `${m.categorie}|${m.periode}`
              const dt = parseDate(m.date_echeance)
              return (
                <div key={i} className="list-row">
                  {dt && (
                    <div className="list-date">
                      <div className="list-date-day">{dt.day}</div>
                      <div className="list-date-month">{dt.month}</div>
                    </div>
                  )}
                  <div className="list-body">
                    <div className="list-title">{m.titre}</div>
                    {m.penalite && <div className="list-sub">{m.penalite}</div>}
                  </div>
                  {onDeclarer && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      disabled={enCours === cle}
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDeclarer(m, cle)
                      }}
                    >
                      {enCours === cle ? 'Envoi…' : 'Marquer comme déclaré'}
                    </button>
                  )}
                </div>
              )
            })}

            {erreur && (
              <div style={{ fontSize: 11.5, padding: '8px 18px 0', color: 'var(--critique)' }}>{erreur}</div>
            )}

            <div style={{ fontSize: 11.5, padding: '10px 18px', color: 'var(--ardoise)', lineHeight: 1.5 }}>
              {data.avertissement} Une échéance marquée « déclaré » par erreur peut être
              corrigée : dites-le au comptable qui gère le dossier.
            </div>
          </div>
        </>
      )}
    </div>
  )
}
