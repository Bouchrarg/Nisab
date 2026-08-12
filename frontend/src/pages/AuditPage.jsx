import { RefreshCw, Search } from 'lucide-react'
import FindingCard from '../components/audit/FindingCard'
import { severityToCls } from '../utils/severity'

// Date de la dernière analyse, en clair. Elle n'avait pas à être affichée
// tant que l'audit se relançait tout seul à l'ouverture : ce qu'on voyait
// venait forcément d'être calculé. Depuis qu'il faut cliquer, l'utilisateur
// doit pouvoir dire si ce rapport date d'une minute ou de trois semaines.
function formatAuditDate(iso) {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleString('fr-MA', { dateStyle: 'long', timeStyle: 'short' })
}

// AuditPage reste purement presentationnel : il ne fetch rien et ne decide
// rien, il descend les props du shell vers les cartes. Les callbacks du
// workflow de correction suivent le meme chemin.
export default function AuditPage({
  findings, technicalFailures = [], inconclusive = [], error, onRunAudit, loading, hasData,
  propositions = {}, onProposer, onVoirProposition, propositionEnCours,
  corpusSources = [], sourceAudit = '', onChangeSourceAudit, onConfirmerRetenueSource,
  auditStatus = 'jamais_lance', auditDate = null, resultatPerime = false,
}) {
  if (!hasData) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon"><Search size={22} /></div>
        <div className="empty-state-title">Aucune donnée à analyser</div>
        <div className="empty-state-sub">Chargez d'abord des données comptables via l'onglet Synchronisation ERP.</div>
      </div>
    )
  }
  // "non_calculable" n'entre jamais dans le total : ce sont des anomalies où
  // une règle a explicitement dit qu'elle ne pouvait rien chiffrer, pas des
  // zéros vérifiés. Les compter comme 0 DH sous-estimerait silencieusement
  // l'exposition réelle — le total affiché doit dire clairement qu'il ne
  // couvre pas tout, plutôt que paraître exhaustif.
  const nonChiffrables = findings.filter(f => f.categorie_montant === 'non_calculable').length
  const total = findings.reduce((s, f) => s + (f.categorie_montant === 'non_calculable' ? 0 : (f.amount_risk || 0)), 0)
  const byLevel = { critique: 0, vigilance: 0, conforme: 0 }
  findings.forEach(f => { byLevel[severityToCls(f.severity)]++ })
  const hasTechnicalFailures = technicalFailures.length > 0
  const hasInconclusive = inconclusive.length > 0
  const jamaisLance = auditStatus === 'jamais_lance'
  const dateLisible = formatAuditDate(auditDate)

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-title">Rapport d'audit fiscal</div>
          <div className="section-sub">
            {jamaisLance ? (
              "Ce dossier n'a pas encore été analysé."
            ) : (
              <>
                <span className="mono">{findings.length}</span> anomalie(s) détectée(s) — Exposition chiffrable :{' '}
                <span className="mono" style={{ color: 'var(--critique)' }}>{total.toLocaleString('fr-MA')} DH</span>
                {nonChiffrables > 0 && (
                  <> · <span className="mono">{nonChiffrables}</span> anomalie(s) sans montant chiffrable automatiquement (hors total)</>
                )}
                {dateLisible && <> · Analyse du {dateLisible}</>}
              </>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <select
            value={sourceAudit}
            onChange={(e) => onChangeSourceAudit?.(e.target.value)}
            disabled={loading}
            title="Source du corpus contre laquelle auditer — par défaut, toutes les sources valides sans distinction de millésime."
            style={{ fontSize: 11, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--bordure)' }}
          >
            <option value="">Toutes les sources valides</option>
            {corpusSources.map((s) => (
              <option key={s.document_id} value={s.document_id}>
                {s.label}{s.date_version ? ` (${s.date_version})` : ''}
              </option>
            ))}
          </select>
          <button className="btn btn-primary btn-sm" onClick={onRunAudit} disabled={loading}>
            {loading ? <span className="spinner" /> : <Search size={13} />}
            {jamaisLance ? "Lancer l'analyse" : "Relancer l'analyse"}
          </button>
        </div>
      </div>

      {loading && (
        <div className="alert info" style={{ marginBottom: 16 }}>
          <div className="alert-dot" />
          <div>
            Analyse en cours — chaque écriture est confrontée au corpus fiscal, ça peut prendre plusieurs minutes pour un gros dossier.
          </div>
        </div>
      )}

      {error && (
        <div className="alert critique" style={{ marginBottom: 16 }}>
          <div className="alert-dot" />
          <div><strong>Échec de l'analyse</strong> — {error}</div>
        </div>
      )}

      {/* Le résultat affiché n'a pas été produit sur les données (ou le
          millésime) actuellement sélectionnés. Avant, ce cas déclenchait un
          ré-audit automatique et silencieux ; on le signale désormais, et
          c'est l'utilisateur qui décide de payer les quelques minutes. */}
      {!loading && !jamaisLance && resultatPerime && (
        <div className="alert info" style={{ marginBottom: 16 }}>
          <div className="alert-dot" />
          <div>
            <strong>Ce rapport n'est plus à jour</strong> — les données comptables ou le millésime de corpus ont changé
            depuis {dateLisible ? `l'analyse du ${dateLisible}` : 'la dernière analyse'}. Relancez l'analyse pour le mettre à jour.
          </div>
        </div>
      )}

      {!loading && hasTechnicalFailures && (
        <div className="alert vigilance" style={{ marginBottom: 16 }}>
          <div className="alert-dot" />
          <div>
            <strong>{technicalFailures.length} écriture(s) non concluante(s)</strong> pour raison technique (quota LLM
            saturé), même après une nouvelle tentative — ce n'est pas un résultat de conformité, relancez l'analyse
            plus tard pour les couvrir.
          </div>
        </div>
      )}

      {!loading && hasInconclusive && (
        <div className="alert vigilance" style={{ marginBottom: 16 }}>
          <div className="alert-dot" />
          <div>
            <strong>{inconclusive.length} écriture(s) à vérifier manuellement</strong> — le corpus fiscal disponible
            ne permet pas de conclure avec certitude sur ces écritures (ce n'est pas un résultat de conformité) :
            <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
              {inconclusive.map((item, i) => (
                <li key={i} style={{ fontSize: 12.5, marginBottom: 2 }}>
                  <span className="mono" style={{ fontWeight: 600 }}>{item.invoice}</span> — {item.description}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Masqués tant qu'aucune analyse n'a tourné : trois compteurs à zéro
          se lisent comme « zéro anomalie », pas comme « rien n'a été mesuré ». */}
      {!jamaisLance && (
        <div className="kpi-grid" style={{ marginBottom: 16 }}>
          {[
            { label: 'Critique', value: byLevel.critique, cls: 'critique' },
            { label: 'Modéré', value: byLevel.vigilance, cls: 'vigilance' },
            { label: 'Faible', value: byLevel.conforme, cls: 'conforme' },
          ].map(({ label, value, cls }) => (
            <div className="kpi-card" key={label}>
              <div className="kpi-label">Niveau {label}</div>
              <div className={`kpi-value ${cls}`}>{value}</div>
              <div className="kpi-sub">anomalie(s)</div>
            </div>
          ))}
        </div>
      )}

      {/* Trois états distincts derrière « zéro anomalie affichée », et non
          plus un seul. Le bandeau vert s'affichait dès que la liste était
          vide — y compris sur un dossier que PERSONNE n'avait jamais analysé :
          le produit certifiait une « bonne conformité » sans qu'aucune
          vérification n'ait eu lieu. C'est exactement l'affirmation sans
          fondement que le reste du produit s'interdit. */}
      {loading ? null : jamaisLance ? (
        <div className="empty-state">
          <div className="empty-state-icon"><RefreshCw size={22} /></div>
          <div className="empty-state-title">Aucune analyse lancée sur ce dossier</div>
          <div className="empty-state-sub">
            Les données comptables sont chargées, mais elles n'ont pas encore été confrontées au corpus fiscal.
            L'analyse dure quelques minutes sur un gros dossier — elle ne démarre que si vous la demandez.
          </div>
          <button className="btn btn-primary btn-sm" style={{ marginTop: 12 }} onClick={onRunAudit}>
            <Search size={13} /> Lancer l'analyse
          </button>
        </div>
      ) : findings.length === 0 ? (
        hasTechnicalFailures || hasInconclusive ? (
          <div className="empty-state-sub">Aucune anomalie parmi les écritures effectivement analysées.</div>
        ) : (
          <div className="alert conforme">
            <div className="alert-dot" />
            <div>
              <strong>Aucune anomalie fiscale détectée</strong> — Le dossier présente une bonne conformité au regard des règles
              {sourceAudit ? ` de ${corpusSources.find((s) => s.document_id === sourceAudit)?.label || sourceAudit}` : ' du corpus'} analysées.
            </div>
          </div>
        )
      ) : (
        <div className="findings-list">
          {findings.map((f, i) => <FindingCard
              key={f.id || i}
              f={f}
              proposition={propositions[f.id]}
              onProposer={onProposer}
              onVoirProposition={onVoirProposition}
              propositionEnCours={propositionEnCours === f.id}
              onConfirmerRetenueSource={onConfirmerRetenueSource}
            />)}
        </div>
      )}
    </div>
  )
}
