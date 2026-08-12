import { useState } from 'react'
import { ChevronDown, ChevronRight, FileWarning } from 'lucide-react'

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
 * `onDeclarer` (optionnel) : appelé avec la ligne manquante quand le cabinet
 * clique « Marquer comme déclaré ». Le composant ne connaît pas l'API — c'est
 * CalendarPage qui fait le POST et recharge la réconciliation — ce composant
 * gère juste l'état de chargement/erreur local le temps de l'appel.
 */
export default function ReconciliationBanner({ data, onDeclarer }) {
  const [ouvert, setOuvert] = useState(false)
  const [enCours, setEnCours] = useState(null) // clé de la ligne en cours de déclaration
  const [erreur, setErreur] = useState(null)
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

  const categories = Object.entries(data.par_categorie || {})
    .sort((a, b) => b[1] - a[1])
    .map(([nom, n]) => `${nom} (${n})`)
    .join(' · ')

  return (
    <div className="alert critique" style={{ marginBottom: 16, flexDirection: 'column', alignItems: 'stretch' }}>
      <div
        style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer' }}
        onClick={() => setOuvert((o) => !o)}
      >
        <FileWarning size={14} style={{ flexShrink: 0, marginTop: 2 }} />
        <div style={{ flex: 1 }}>
          <strong>
            {manquantes.length} obligation(s) échue(s) sans trace de dépôt ni de paiement
          </strong>
          <div style={{ fontSize: 12, marginTop: 3, opacity: 0.85 }}>{categories}</div>
        </div>
        {ouvert ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
      </div>

      {ouvert && (
        <div style={{ marginTop: 12, borderTop: '1px solid rgba(0,0,0,0.08)', paddingTop: 10 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--sourdine)' }}>
                <th style={{ padding: '4px 8px 6px 0', fontWeight: 600 }}>Échéance</th>
                <th style={{ padding: '4px 8px 6px 0', fontWeight: 600 }}>Obligation</th>
                <th style={{ padding: '4px 8px 6px 0', fontWeight: 600 }}>Majoration encourue</th>
                {onDeclarer && <th style={{ padding: '4px 0 6px 0', fontWeight: 600 }} />}
              </tr>
            </thead>
            <tbody>
              {manquantes.map((m, i) => {
                const cle = `${m.categorie}|${m.periode}`
                return (
                  <tr key={i} style={{ borderTop: '1px solid rgba(0,0,0,0.06)' }}>
                    <td className="mono" style={{ padding: '6px 8px 6px 0', whiteSpace: 'nowrap' }}>{m.date_echeance}</td>
                    <td style={{ padding: '6px 8px 6px 0' }}>{m.titre}</td>
                    <td style={{ padding: '6px 8px 6px 0', opacity: 0.85 }}>{m.penalite || '—'}</td>
                    {onDeclarer && (
                      <td style={{ padding: '6px 0', textAlign: 'right', whiteSpace: 'nowrap' }}>
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
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>

          {erreur && (
            <div style={{ fontSize: 11.5, marginTop: 8, color: 'var(--critique, #C0281C)' }}>{erreur}</div>
          )}

          <div style={{ fontSize: 11.5, marginTop: 10, opacity: 0.8, lineHeight: 1.5 }}>
            {data.avertissement} Une échéance marquée « déclaré » par erreur peut être
            corrigée : dites-le au comptable qui gère le dossier.
          </div>
        </div>
      )}
    </div>
  )
}
