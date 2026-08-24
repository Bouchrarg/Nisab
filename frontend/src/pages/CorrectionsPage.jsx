import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Check, ExternalLink, RefreshCw, Send, Save, X } from 'lucide-react'
import Badge from '../components/ui/Badge'
import CitationPills from '../components/audit/CitationPills'
import { dossierFetch } from '../config/api'
import { useDossier } from '../context/DossierContext'

const STATUTS = {
  en_attente: { label: 'À valider', cls: 'neutral' },
  validee: { label: 'Validée', cls: 'conforme' },
  rejetee: { label: 'Rejetée', cls: 'critique' },
  poussee: { label: 'Dans Odoo', cls: 'seuil' },
  erreur: { label: 'Échec Odoo', cls: 'critique' },
}

const TYPES = {
  ecriture_od: "Écriture d'opérations diverses",
  regularisation_tva: 'Régularisation de TVA',
  piece_a_reclamer: 'Pièce à réclamer',
  aucune_ecriture: 'Aucune écriture possible',
}

const dh = (n) => `${Number(n || 0).toLocaleString('fr-MA', { minimumFractionDigits: 2 })} DH`

async function lire(res, defaut) {
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || defaut)
  }
  return res.json()
}

/**
 * File de validation humaine des corrections proposées par l'IA.
 *
 * Reprend le patron maître/détail d'AdminPage : c'est déjà l'écran de revue
 * du projet, et un utilisateur qui sait valider un corpus sait valider une
 * correction sans réapprendre une interface.
 *
 * Le point central de l'écran est le total débit / crédit / écart sous la
 * table des lignes. Tant que l'écart n'est pas nul, « Enregistrer » et
 * « Valider » sont désactivés — la même règle que le backend applique, rendue
 * visible avant l'aller-retour serveur plutôt qu'après.
 */
export default function CorrectionsPage() {
  const { activeDossier } = useDossier()
  const [propositions, setPropositions] = useState([])
  const [selection, setSelection] = useState(null)
  const [detail, setDetail] = useState(null)
  const [lignes, setLignes] = useState([])
  const [loading, setLoading] = useState(true)
  const [action, setAction] = useState(null)
  const [erreur, setErreur] = useState(null)
  const [succes, setSucces] = useState(null)
  const [motifRejet, setMotifRejet] = useState(null)

  const charger = useCallback(async () => {
    setLoading(true)
    setErreur(null)
    try {
      const data = await lire(await dossierFetch('/propositions'), 'Chargement impossible.')
      setPropositions(data.propositions || [])
    } catch (e) {
      setErreur(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (activeDossier) charger()
  }, [activeDossier, charger])

  const ouvrir = async (p) => {
    setSelection(p.id)
    setDetail(null)
    setSucces(null)
    setErreur(null)
    setMotifRejet(null)
    try {
      const d = await lire(await dossierFetch(`/propositions/${p.id}`), 'Détail indisponible.')
      setDetail(d)
      setLignes(d.lignes || [])
    } catch (e) {
      setErreur(e.message)
    }
  }

  const totaux = useMemo(() => {
    const debit = lignes.reduce((s, l) => s + Number(l.debit || 0), 0)
    const credit = lignes.reduce((s, l) => s + Number(l.credit || 0), 0)
    return { debit, credit, ecart: Math.round((debit - credit) * 100) / 100 }
  }, [lignes])

  const equilibree = Math.abs(totaux.ecart) < 0.005
  const modifiable = detail?.statut === 'en_attente'
  const avecEcriture = detail?.peut_etre_poussee

  const majLigne = (i, champ, valeur) => {
    setLignes((prev) => prev.map((l, idx) => (idx === i ? { ...l, [champ]: valeur } : l)))
  }

  const appeler = async (chemin, options, message) => {
    setAction(chemin)
    setErreur(null)
    setSucces(null)
    try {
      const d = await lire(await dossierFetch(chemin, options), 'Opération refusée.')
      setDetail((prev) => ({ ...prev, ...d }))
      setLignes(d.lignes || [])
      setSucces(d.message || message)
      await charger()
    } catch (e) {
      setErreur(e.message)
    } finally {
      setAction(null)
    }
  }

  if (!activeDossier) return null

  return (
    <div>
      <div className="section-header" style={{ alignItems: 'center' }}>
        <div>
          <div className="section-sub">
            L'IA propose une écriture sourcée pour chaque anomalie ; rien ne part vers l'ERP sans votre validation.
          </div>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={charger} disabled={loading}>
          {loading ? <span className="spinner dark" /> : <RefreshCw size={13} />} Actualiser
        </button>
      </div>

      {erreur && (
        <div className="alert critique" style={{ marginBottom: 14 }}>
          <div className="alert-dot" /><div>{erreur}</div>
        </div>
      )}
      {succes && (
        <div className="alert conforme" style={{ marginBottom: 14 }}>
          <div className="alert-dot" /><div>{succes}</div>
        </div>
      )}

      {!loading && propositions.length === 0 ? (
        <div className="empty-state">
          <AlertTriangle size={22} className="empty-state-icon" />
          <div className="empty-state-title">Aucune proposition pour l'instant</div>
          <div className="empty-state-sub">
            Ouvrez l'onglet Audit et cliquez sur « Proposer une correction » sur une anomalie.
          </div>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, alignItems: 'start' }}>

          {/* ── Liste ────────────────────────────────────────────────── */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">{propositions.length} proposition(s)</span>
            </div>
            <div className="card-body" style={{ padding: 0 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--bordure)', textAlign: 'left', color: 'var(--sourdine)', fontSize: 11 }}>
                    <th style={{ padding: '8px 12px', fontWeight: 600 }}>Statut</th>
                    <th style={{ padding: '8px 12px', fontWeight: 600 }}>Pièce</th>
                    <th style={{ padding: '8px 12px', fontWeight: 600 }}>Correction</th>
                    <th style={{ padding: '8px 12px', fontWeight: 600, textAlign: 'right' }}>Impact</th>
                  </tr>
                </thead>
                <tbody>
                  {propositions.map((p) => (
                    <tr
                      key={p.id}
                      onClick={() => ouvrir(p)}
                      style={{
                        borderBottom: '1px solid var(--bordure)',
                        cursor: 'pointer',
                        background: selection === p.id ? 'var(--surface-2)' : 'transparent',
                      }}
                    >
                      <td style={{ padding: '10px 12px' }}>
                        <Badge cls={STATUTS[p.statut]?.cls || 'neutral'}>{STATUTS[p.statut]?.label || p.statut}</Badge>
                      </td>
                      <td className="mono" style={{ padding: '10px 12px', fontSize: 11.5 }}>
                        {p.cle_metier?.split('|')[0] || '—'}
                      </td>
                      <td style={{ padding: '10px 12px' }}>{p.resume}</td>
                      <td className="mono" style={{ padding: '10px 12px', textAlign: 'right' }}>
                        {p.categorie_montant === 'non_calculable'
                          ? <span style={{ color: 'var(--sourdine)', fontWeight: 400 }}>non chiffrable</span>
                          : (p.montant_impact ? dh(p.montant_impact) : '—')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* ── Détail ───────────────────────────────────────────────── */}
          <div className="card">
            {!detail ? (
              <div className="card-body">
                <div style={{ fontSize: 13, color: 'var(--sourdine)' }}>
                  Sélectionnez une proposition pour l'examiner.
                </div>
              </div>
            ) : (
              <>
                <div className="card-header">
                  <span className="card-title">{TYPES[detail.type_correction] || detail.type_correction}</span>
                  <Badge cls={STATUTS[detail.statut]?.cls || 'neutral'}>
                    {STATUTS[detail.statut]?.label || detail.statut}
                  </Badge>
                </div>
                <div className="card-body">

                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--encre)', marginBottom: 6 }}>
                    {detail.resume}
                  </div>
                  <div style={{ fontSize: 12.5, color: 'var(--ardoise)', lineHeight: 1.6, marginBottom: 14 }}>
                    {detail.justification}
                  </div>

                  <CitationPills
                    principale={detail.references?.[0]}
                    secondaires={detail.references?.slice(1)}
                    titre="Articles invoqués — cliquez pour lire le texte"
                  />

                  {/* Montant copié tel quel depuis l'alerte d'audit (jamais
                      recalculé, jamais redemandé au LLM — cf. correction_agent).
                      "non_calculable" reste affiché : la raison légale de
                      l'absence de montant est une information en soi. */}
                  {(detail.montant_detail || detail.categorie_montant) && (
                    <div style={{ margin: '12px 0', padding: '8px 12px', background: 'var(--toile)', border: '1px solid var(--bordure)', borderRadius: 'var(--radius-sm)' }}>
                      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--sourdine)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 4 }}>
                        {detail.categorie_montant === 'non_calculable'
                          ? 'Montant non chiffrable automatiquement'
                          : detail.categorie_montant === 'calculable_hypothese'
                            ? 'Impact financier (sous hypothèse)'
                            : 'Impact financier calculé'}
                      </div>
                      {detail.montant_impact != null && detail.categorie_montant !== 'non_calculable' && (
                        <div className="mono" style={{ fontSize: 13, fontWeight: 700, color: 'var(--critique)', marginBottom: 4 }}>
                          {dh(detail.montant_impact)}
                        </div>
                      )}
                      {detail.montant_detail && (
                        <div style={{ fontSize: 11.5, color: 'var(--ardoise)', lineHeight: 1.5 }}>{detail.montant_detail}</div>
                      )}
                      {detail.montant_hypothese && (
                        <div style={{ fontSize: 11, color: 'var(--seuil)', lineHeight: 1.5, fontStyle: 'italic', marginTop: 4 }}>
                          Hypothèse : {detail.montant_hypothese}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Une proposition amendée doit se voir : c'est la frontière
                      entre ce que la machine a produit et ce que l'humain a
                      décidé. */}
                  {detail.amendee && (
                    <div className="alert vigilance" style={{ marginBottom: 12 }}>
                      <div className="alert-dot" />
                      <div style={{ fontSize: 12 }}>
                        Cette proposition a été modifiée manuellement — la version initiale de l'IA est conservée en base.
                      </div>
                    </div>
                  )}

                  {avecEcriture ? (
                    <>
                      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--sourdine)', letterSpacing: '0.08em', textTransform: 'uppercase', margin: '14px 0 6px' }}>
                        Écriture proposée
                      </div>
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                        <thead>
                          <tr style={{ textAlign: 'left', color: 'var(--sourdine)', fontSize: 10.5 }}>
                            <th style={{ padding: '4px 6px 6px 0', fontWeight: 600 }}>Compte</th>
                            <th style={{ padding: '4px 6px 6px 0', fontWeight: 600 }}>Libellé</th>
                            <th style={{ padding: '4px 6px 6px 0', fontWeight: 600, textAlign: 'right' }}>Débit</th>
                            <th style={{ padding: '4px 0 6px 0', fontWeight: 600, textAlign: 'right' }}>Crédit</th>
                          </tr>
                        </thead>
                        <tbody>
                          {lignes.map((l, i) => (
                            <tr key={i} style={{ borderTop: '1px solid var(--bordure)' }}>
                              <td style={{ padding: '4px 6px 4px 0' }}>
                                <input className="form-input mono" style={{ padding: '4px 6px', fontSize: 11.5 }}
                                  value={l.compte || ''} disabled={!modifiable}
                                  onChange={(e) => majLigne(i, 'compte', e.target.value)} />
                              </td>
                              <td style={{ padding: '4px 6px 4px 0' }}>
                                <input className="form-input" style={{ padding: '4px 6px', fontSize: 11.5 }}
                                  value={l.libelle || ''} disabled={!modifiable}
                                  onChange={(e) => majLigne(i, 'libelle', e.target.value)} />
                              </td>
                              <td style={{ padding: '4px 6px 4px 0' }}>
                                <input className="form-input mono" type="number" step="0.01"
                                  style={{ padding: '4px 6px', fontSize: 11.5, textAlign: 'right' }}
                                  value={l.debit ?? 0} disabled={!modifiable}
                                  onChange={(e) => majLigne(i, 'debit', Number(e.target.value))} />
                              </td>
                              <td style={{ padding: '4px 0' }}>
                                <input className="form-input mono" type="number" step="0.01"
                                  style={{ padding: '4px 6px', fontSize: 11.5, textAlign: 'right' }}
                                  value={l.credit ?? 0} disabled={!modifiable}
                                  onChange={(e) => majLigne(i, 'credit', Number(e.target.value))} />
                              </td>
                            </tr>
                          ))}
                        </tbody>
                        <tfoot>
                          <tr style={{ borderTop: '2px solid var(--bordure)' }}>
                            <td colSpan={2} style={{ padding: '8px 6px 4px 0', fontWeight: 600 }}>Totaux</td>
                            <td className="mono" style={{ padding: '8px 6px 4px 0', textAlign: 'right' }}>{dh(totaux.debit)}</td>
                            <td className="mono" style={{ padding: '8px 0 4px', textAlign: 'right' }}>{dh(totaux.credit)}</td>
                          </tr>
                          <tr>
                            <td colSpan={3} style={{ padding: '2px 6px 0 0', fontWeight: 600, color: equilibree ? 'var(--conforme)' : 'var(--critique)' }}>
                              {equilibree ? 'Écriture équilibrée' : 'Écart'}
                            </td>
                            <td className="mono" style={{ padding: '2px 0 0', textAlign: 'right', fontWeight: 700, color: equilibree ? 'var(--conforme)' : 'var(--critique)' }}>
                              {equilibree ? '—' : dh(Math.abs(totaux.ecart))}
                            </td>
                          </tr>
                        </tfoot>
                      </table>
                    </>
                  ) : (
                    <div className="alert info" style={{ marginTop: 12 }}>
                      <div className="alert-dot" />
                      <div style={{ fontSize: 12.5 }}>
                        <strong>Aucune écriture comptable ne corrige cette anomalie.</strong>
                        {detail.action && <> Action à mener : {detail.action}</>}
                      </div>
                    </div>
                  )}

                  {detail.erreur_message && (
                    <div className="alert critique" style={{ marginTop: 12 }}>
                      <div className="alert-dot" />
                      <div style={{ fontSize: 12 }}><strong>Dernier échec Odoo</strong> — {detail.erreur_message}</div>
                    </div>
                  )}

                  {detail.odoo_url && (
                    <div className="alert conforme" style={{ marginTop: 12 }}>
                      <div className="alert-dot" />
                      <div style={{ fontSize: 12.5 }}>
                        Brouillon créé dans Odoo — <strong>il n'est pas validé</strong>, relisez-le puis postez-le depuis l'ERP.{' '}
                        <a href={detail.odoo_url} target="_blank" rel="noreferrer" style={{ color: 'var(--seuil)', fontWeight: 600 }}>
                          Ouvrir dans Odoo <ExternalLink size={11} style={{ verticalAlign: -1 }} />
                        </a>
                      </div>
                    </div>
                  )}

                  {/* ── Actions ─────────────────────────────────────── */}
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 16 }}>
                    {modifiable && avecEcriture && (
                      <button className="btn btn-secondary btn-sm" disabled={!equilibree || !!action}
                        onClick={() => appeler(`/propositions/${detail.id}`, {
                          method: 'PATCH', body: JSON.stringify({ lignes }),
                        }, 'Amendement enregistré.')}>
                        <Save size={13} /> Enregistrer l'amendement
                      </button>
                    )}
                    {modifiable && (
                      <button className="btn btn-primary btn-sm" disabled={(avecEcriture && !equilibree) || !!action}
                        onClick={() => appeler(`/propositions/${detail.id}/valider`, { method: 'POST' }, 'Proposition validée.')}>
                        <Check size={13} /> Valider
                      </button>
                    )}
                    {['validee', 'erreur'].includes(detail.statut) && avecEcriture && (
                      <button className="btn btn-primary btn-sm" disabled={!!action}
                        onClick={() => appeler(`/propositions/${detail.id}/pousser`, { method: 'POST' }, 'Brouillon créé.')}>
                        {action?.endsWith('/pousser') ? <span className="spinner" /> : <Send size={13} />}
                        Créer le brouillon dans Odoo
                      </button>
                    )}
                    {detail.statut !== 'rejetee' && detail.statut !== 'poussee' && (
                      <button className="btn btn-danger btn-sm" disabled={!!action}
                        onClick={() => setMotifRejet(motifRejet === null ? '' : null)}>
                        <X size={13} /> Rejeter
                      </button>
                    )}
                  </div>

                  {/* Motif obligatoire, saisi en ligne. Pas de window.confirm :
                      un rejet sans motif ne se distingue pas d'un oubli, et
                      c'est le seul signal exploitable sur ce que l'IA propose
                      de travers. */}
                  {motifRejet !== null && (
                    <div style={{ marginTop: 12 }}>
                      <label className="form-label">Motif du rejet (obligatoire, 5 caractères minimum)</label>
                      <textarea className="form-input" rows={3} value={motifRejet}
                        placeholder="Ex. : le compte proposé n'est pas le bon, la charge est déductible en réalité…"
                        onChange={(e) => setMotifRejet(e.target.value)} />
                      <button className="btn btn-danger btn-sm" style={{ marginTop: 8 }}
                        disabled={motifRejet.trim().length < 5 || !!action}
                        onClick={() => appeler(`/propositions/${detail.id}/rejeter`, {
                          method: 'POST', body: JSON.stringify({ motif: motifRejet.trim() }),
                        }, 'Proposition rejetée.')}>
                        Confirmer le rejet
                      </button>
                    </div>
                  )}

                  {detail.motif_decision && (
                    <div style={{ fontSize: 12, color: 'var(--ardoise)', marginTop: 12 }}>
                      <strong>Motif enregistré :</strong> {detail.motif_decision}
                    </div>
                  )}

                  <div style={{ fontSize: 11, color: 'var(--sourdine)', marginTop: 14, lineHeight: 1.5 }}>
                    Proposition générée par {detail.genere_par_modele || 'un modèle de langage'}, à partir des seuls
                    articles déjà retenus par l'audit. Elle n'a aucune valeur tant qu'un humain ne l'a pas endossée.
                  </div>

                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
