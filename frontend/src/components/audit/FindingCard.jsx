import { useState } from 'react'
import { ChevronDown, ChevronUp, Wand2, ClipboardCheck } from 'lucide-react'
import Badge from '../ui/Badge'
import CitationPills from './CitationPills'
import OdooPathBreadcrumb from './OdooPathBreadcrumb'
import { severityToCls } from '../../utils/severity'

// Libellés des statuts de proposition, et classe de badge associée. Le
// vocabulaire de sévérité du projet (critique/vigilance/conforme/seuil) est
// réutilisé tel quel plutôt que d'inventer des couleurs pour ce seul écran.
const STATUT_PROPOSITION = {
  en_attente: { label: 'Correction à valider', cls: 'neutral' },
  validee: { label: 'Correction validée', cls: 'conforme' },
  rejetee: { label: 'Correction rejetée', cls: 'critique' },
  poussee: { label: 'Brouillon créé dans Odoo', cls: 'seuil' },
  erreur: { label: 'Échec de la création Odoo', cls: 'critique' },
}

// Le montant vient désormais d'une règle déterministe (app.regles_montant
// côté backend), plus jamais d'une estimation libre du LLM — voir
// CorrectionsPage pour la même logique côté proposition de correction.
// "non_calculable" doit rester VISIBLE, pas silencieusement absent : cacher
// la ligne donnerait l'impression qu'aucun montant n'a été envisagé, alors
// qu'une règle a explicitement conclu qu'elle ne pouvait rien affirmer —
// une différence qu'un contrôleur ne doit jamais avoir à deviner.
const LABEL_CATEGORIE_MONTANT = {
  calculable: 'Exposition calculée',
  calculable_hypothese: 'Exposition calculée (sous hypothèse)',
  non_calculable: 'Montant non chiffrable automatiquement',
}

// Même normalisation que app.ai_auditor._normalize_ref côté backend (casse +
// espaces) : reference_cgi vient du LLM, pas d'un enum, donc mieux vaut
// comparer comme le fait la route qui reçoit la confirmation plutôt que de
// risquer un mismatch silencieux entre affichage et validation serveur.
const estArticle151 = (reference) => (reference || '').toLowerCase().split(/\s+/).filter(Boolean).join(' ') === 'article 151'

export default function FindingCard({ f, proposition, onProposer, onVoirProposition, propositionEnCours, onConfirmerRetenueSource }) {
  const [open, setOpen] = useState(false)
  const [retenueChoix, setRetenueChoix] = useState(null) // true | false | null (pas encore tranché dans le formulaire)
  const [retenueMontant, setRetenueMontant] = useState('')
  const [retenueEnCours, setRetenueEnCours] = useState(false)
  const [retenueErreur, setRetenueErreur] = useState(null)
  const [retenueEnEdition, setRetenueEnEdition] = useState(false)
  const cls = severityToCls(f.severity)
  const severityLabel = cls === 'critique' ? 'Critique' : cls === 'vigilance' ? 'Modéré' : 'Faible'
  const montantChiffre = f.categorie_montant !== 'non_calculable' && f.amount_risk > 0
  const montantNonChiffrable = f.categorie_montant === 'non_calculable'
  const dejaConfirme = f.retenue_source_confirmee !== null && f.retenue_source_confirmee !== undefined

  const soumettreRetenue = async () => {
    if (retenueChoix === null) return
    setRetenueEnCours(true)
    setRetenueErreur(null)
    try {
      await onConfirmerRetenueSource?.(f, {
        applicable: retenueChoix,
        montantDu: retenueMontant ? Number(retenueMontant) : null,
      })
      setRetenueEnEdition(false)
    } catch (e) {
      setRetenueErreur(e.message)
    } finally {
      setRetenueEnCours(false)
    }
  }

  return (
    <div className="finding">
      <div className="finding-inner">
        {/* Direction D : plus de réglette de couleur verticale — le Badge
            juste en dessous (carré + texte) porte déjà la sévérité. */}
        <div className="finding-main">

          <div className="finding-head" onClick={() => setOpen(o => !o)} style={{ cursor: 'pointer' }}>
            <div className="finding-left">
              <Badge cls={cls}>{severityLabel}</Badge>
              <span className="finding-title">{f.title || 'Comptabilité non conforme'}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {montantChiffre && (
                <span className="finding-amount mono">
                  {f.categorie_montant === 'calculable_hypothese' ? '≈' : '−'}
                  {Number(f.amount_risk).toLocaleString('fr-MA')} DH
                </span>
              )}
              {montantNonChiffrable && (
                <span className="finding-amount mono" style={{ color: 'var(--sourdine)', fontWeight: 500 }}>
                  Montant non chiffrable
                </span>
              )}
              {open ? <ChevronUp size={14} color="var(--sourdine)" /> : <ChevronDown size={14} color="var(--sourdine)" />}
            </div>
          </div>

          {open && (
            <div className="finding-body">

              {(f.invoice || f.partner || f.date) && (
                <div style={{ background: 'var(--toile)', border: '1px solid var(--bordure)', borderRadius: 6, padding: '10px 14px', marginBottom: 12 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--sourdine)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>
                    Écriture comptable auditée
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px,1fr))', gap: '6px 16px' }}>
                    {f.invoice && (
                      <div>
                        <div style={{ fontSize: 10, color: 'var(--sourdine)' }}>N° Pièce</div>
                        <div style={{ fontSize: 12.5, fontFamily: 'var(--font-mono)', color: 'var(--encre)', fontWeight: 600 }}>{f.invoice}</div>
                      </div>
                    )}
                    {f.partner && (
                      <div>
                        <div style={{ fontSize: 10, color: 'var(--sourdine)' }}>Fournisseur / Tiers</div>
                        <div style={{ fontSize: 12.5, color: 'var(--encre)' }}>{f.partner}</div>
                      </div>
                    )}
                    {f.date && (
                      <div>
                        <div style={{ fontSize: 10, color: 'var(--sourdine)' }}>Date</div>
                        <div style={{ fontSize: 12.5, fontFamily: 'var(--font-mono)', color: 'var(--encre)' }}>{f.date}</div>
                      </div>
                    )}
                    {montantChiffre && (
                      <div>
                        <div style={{ fontSize: 10, color: 'var(--sourdine)' }}>
                          {LABEL_CATEGORIE_MONTANT[f.categorie_montant] || 'Exposition'}
                        </div>
                        <div style={{ fontSize: 12.5, fontFamily: 'var(--font-mono)', color: 'var(--critique)', fontWeight: 700 }}>
                          {Number(f.amount_risk).toLocaleString('fr-MA')} DH
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Le calcul en toutes lettres — jamais un chiffre nu. Un
                      contrôleur DGI (ou l'étudiante qui soutient ce projet)
                      doit pouvoir le vérifier de tête, pas le croire sur
                      parole. Affiché aussi pour non_calculable : la raison
                      légale de l'absence de montant est une information,
                      pas un vide. */}
                  {f.montant_detail && (
                    <div style={{ marginTop: 10, fontSize: 11.5, color: 'var(--sourdine)', lineHeight: 1.5 }}>
                      {f.montant_detail}
                    </div>
                  )}
                  {f.montant_hypothese && (
                    <div style={{ marginTop: 4, fontSize: 11, color: 'var(--seuil)', lineHeight: 1.5, fontStyle: 'italic' }}>
                      Hypothèse : {f.montant_hypothese}
                    </div>
                  )}
                </div>
              )}

              {/* Art. 151 seulement : le RAG ne peut jamais chiffrer cette
                  anomalie seul, le statut du bénéficiaire au regard de la
                  retenue à la source (Art. 15 bis / 45 bis) est une donnée
                  que seul le comptable connaît (regles_montant.py). Sans
                  cette confirmation, l'alerte reste non_calculable pour
                  toujours — ce n'est pas une limite d'affichage, c'est la
                  seule façon de sortir du 0 DH sans inventer un fait. */}
              {onConfirmerRetenueSource && estArticle151(f.reference_cgi) && (
                <div style={{
                  background: 'color-mix(in srgb, var(--critique) 5%, transparent)',
                  border: '1px solid color-mix(in srgb, var(--critique) 18%, transparent)',
                  borderRadius: 6, padding: '10px 12px', marginBottom: 12,
                }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--critique)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 6 }}>
                    Retenue à la source — statut du tiers
                  </div>

                  {dejaConfirme && !retenueEnEdition ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 12.5, color: 'var(--ardoise)' }}>
                        {f.retenue_source_confirmee
                          ? `Confirmé applicable — ${Number(f.retenue_montant_du || 0).toLocaleString('fr-MA')} DH de retenue due.`
                          : 'Confirmé non applicable — aucune majoration.'}
                      </span>
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => {
                          setRetenueChoix(f.retenue_source_confirmee)
                          setRetenueMontant(f.retenue_montant_du != null ? String(f.retenue_montant_du) : '')
                          setRetenueEnEdition(true)
                        }}
                      >
                        Modifier
                      </button>
                    </div>
                  ) : (
                    <div>
                      <div style={{ fontSize: 12.5, color: 'var(--ardoise)', marginBottom: 8 }}>
                        Ce tiers relève-t-il d'un régime de retenue à la source ?
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <button
                          className={`btn btn-sm ${retenueChoix === true ? 'btn-primary' : 'btn-secondary'}`}
                          onClick={() => setRetenueChoix(true)}
                        >
                          Oui
                        </button>
                        <button
                          className={`btn btn-sm ${retenueChoix === false ? 'btn-primary' : 'btn-secondary'}`}
                          onClick={() => setRetenueChoix(false)}
                        >
                          Non
                        </button>
                        {retenueChoix === true && (
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            placeholder="Montant de la retenue due (DH)"
                            value={retenueMontant}
                            onChange={(e) => setRetenueMontant(e.target.value)}
                            style={{ fontSize: 12, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--bordure)', width: 200 }}
                          />
                        )}
                        {retenueChoix !== null && (
                          <button
                            className="btn btn-primary btn-sm"
                            onClick={soumettreRetenue}
                            disabled={retenueEnCours || (retenueChoix === true && !retenueMontant)}
                          >
                            {retenueEnCours ? <span className="spinner dark" /> : 'Confirmer'}
                          </button>
                        )}
                      </div>
                      {retenueChoix === true && !retenueMontant && (
                        <div style={{ fontSize: 11, color: 'var(--sourdine)', marginTop: 4 }}>
                          Sans montant, la règle renverra 0 DH même sur « applicable » — la donnée est requise pour chiffrer.
                        </div>
                      )}
                      {retenueErreur && (
                        <div style={{ fontSize: 11, color: 'var(--critique)', marginTop: 4 }}>{retenueErreur}</div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* `source` = le millésime réellement audité, pas un libellé
                  figé : l'audit peut être contraint à un document précis via
                  le sélecteur d'AuditPage (?document_id=cgi_2024). Absent sur
                  les alertes antérieures à ce champ — on n'affiche alors rien
                  plutôt qu'un millésime supposé. */}
              <CitationPills
                principale={f.reference_cgi}
                secondaires={f.rag_sources}
                source={f.version_corpus}
              />

              {f.description && (
                <div style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--sourdine)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 4 }}>
                    Constat
                  </div>
                  <div style={{ fontSize: 12.5, color: 'var(--ardoise)', lineHeight: 1.6 }}>{f.description}</div>
                </div>
              )}

              {f.recommendation && (
                <div style={{
                  background: 'color-mix(in srgb, var(--seuil) 6%, transparent)',
                  border: '1px solid color-mix(in srgb, var(--seuil) 20%, transparent)',
                  borderRadius: 6, padding: '8px 12px',
                }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--seuil)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 4 }}>
                    Recommandation
                  </div>
                  <div style={{ fontSize: 12.5, color: 'var(--ardoise)', lineHeight: 1.55 }}>{f.recommendation}</div>
                </div>
              )}

              {/* Point d'entrée du workflow agentique : proposer une correction
                  sourcée pour cette anomalie, puis la faire valider par un humain.
                  Rendu seulement si le parent fournit le callback, pour que
                  FindingCard reste utilisable ailleurs sans ce workflow. */}
              {onProposer && (
                <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  {proposition ? (
                    <>
                      <Badge cls={STATUT_PROPOSITION[proposition.statut]?.cls || 'neutral'}>
                        {STATUT_PROPOSITION[proposition.statut]?.label || proposition.statut}
                      </Badge>
                      <button className="btn btn-secondary btn-sm" onClick={() => onVoirProposition?.(proposition)}>
                        <ClipboardCheck size={13} /> Voir la proposition
                      </button>
                    </>
                  ) : (
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => onProposer(f)}
                      disabled={propositionEnCours}
                    >
                      {propositionEnCours ? <span className="spinner dark" /> : <Wand2 size={13} />}
                      Proposer une correction
                    </button>
                  )}
                </div>
              )}

              {f.odoo_path && (
                <OdooPathBreadcrumb path={f.odoo_path} />
              )}

            </div>
          )}

        </div>
      </div>
    </div>
  )
}
