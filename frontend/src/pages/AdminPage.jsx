import { useCallback, useEffect, useState } from 'react'
import {
  RefreshCw, PlayCircle, Radio, CheckSquare, CheckCircle2, Trash2,
  Database, Clock, ChevronLeft, ChevronRight,
} from 'lucide-react'
import Badge from '../components/ui/Badge'
import { API_URL } from '../config/api'

export default function AdminPage() {
  const [stats, setStats] = useState(null)
  const [sources, setSources] = useState([])
  const [log, setLog] = useState([])
  const [loadingStats, setLoadingStats] = useState(true)
  const [pipelineRunning, setPipelineRunning] = useState(false)
  const [monitorRunning, setMonitorRunning] = useState(false)
  const [lastPipelineResult, setLastPipelineResult] = useState(null)
  const [lastMonitorResult, setLastMonitorResult] = useState(null)

  const [articles, setArticles] = useState([])
  const [articlesTotal, setArticlesTotal] = useState(0)
  const [articlesPage, setArticlesPage] = useState(1)
  const [articlesPages, setArticlesPages] = useState(1)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [activeArticle, setActiveArticle] = useState(null)
  const [loadingArticles, setLoadingArticles] = useState(false)
  const [articleFilter, setArticleFilter] = useState('a_verifier')
  const [dedupeResult, setDedupeResult] = useState(null)
  const [ingestRunning, setIngestRunning] = useState(false)

  const fetchAll = useCallback(async () => {
    setLoadingStats(true)
    try {
      const [sRes, srcRes, logRes] = await Promise.all([
        fetch(`${API_URL}/admin/corpus/stats`),
        fetch(`${API_URL}/admin/corpus/sources`),
        fetch(`${API_URL}/admin/pipeline/log`),
      ])
      if (sRes.ok) setStats(await sRes.json())
      if (srcRes.ok) {
        const d = await srcRes.json()
        setSources(d.sources || [])
      }
      if (logRes.ok) {
        const d = await logRes.json()
        setLog(d.log || [])
      }
    } finally {
      setLoadingStats(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
  }, [fetchAll])

  const fetchArticles = useCallback(async (page = 1, statut = articleFilter) => {
    setLoadingArticles(true)
    try {
      const res = await fetch(`${API_URL}/admin/articles?statut=${statut}&page=${page}&limit=30`)
      if (res.ok) {
        const d = await res.json()
        setArticles(d.articles || [])
        setArticlesTotal(d.total || 0)
        setArticlesPage(d.page || 1)
        setArticlesPages(d.pages || 1)
        setSelectedIds(new Set())
      }
    } finally {
      setLoadingArticles(false)
    }
  }, [articleFilter])

  useEffect(() => {
    fetchArticles(1, articleFilter)
  }, [articleFilter, fetchArticles])

  const openArticle = async (id) => {
    const res = await fetch(`${API_URL}/admin/articles/${id}`)
    if (res.ok) setActiveArticle(await res.json())
  }

  const validateSelected = async () => {
    const ids = [...selectedIds]
    if (!ids.length) return
    await fetch(`${API_URL}/admin/articles/validate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    })
    fetchArticles(articlesPage, articleFilter)
    fetchAll()
  }

  const validateAllPending = async () => {
    if (!window.confirm(`Valider les ${articlesTotal} articles en attente ?`)) return
    await fetch(`${API_URL}/admin/articles/validate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ all_pending: true }),
    })
    fetchArticles(1, articleFilter)
    fetchAll()
  }

  const rejectSelected = async () => {
    const ids = [...selectedIds]
    if (!ids.length || !window.confirm(`Supprimer ${ids.length} article(s) ?`)) return
    await fetch(`${API_URL}/admin/articles/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    })
    setActiveArticle(null)
    fetchArticles(articlesPage, articleFilter)
    fetchAll()
  }

  const deduplicate = async () => {
    const res = await fetch(`${API_URL}/admin/articles/deduplicate`, { method: 'POST' })
    if (res.ok) {
      setDedupeResult(await res.json())
      fetchArticles(articlesPage, articleFilter)
      fetchAll()
    }
  }

  const triggerIngest = async () => {
    setIngestRunning(true)
    try {
      await fetch(`${API_URL}/admin/ingest/run`, { method: 'POST' })
      fetchAll()
    } finally {
      setIngestRunning(false)
    }
  }

  const toggleSelect = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === articles.length) setSelectedIds(new Set())
    else setSelectedIds(new Set(articles.map((a) => a.id)))
  }

  const triggerPipeline = async () => {
    setPipelineRunning(true)
    setLastPipelineResult(null)
    try {
      const res = await fetch(`${API_URL}/admin/pipeline/run`, { method: 'POST' })
      const d = await res.json()
      setLastPipelineResult(d)
      fetchAll()
    } finally {
      setPipelineRunning(false)
    }
  }

  const triggerMonitor = async () => {
    setMonitorRunning(true)
    setLastMonitorResult(null)
    try {
      const res = await fetch(`${API_URL}/admin/monitor/run`, { method: 'POST' })
      const d = await res.json()
      setLastMonitorResult(d)
      fetchAll()
    } finally {
      setMonitorRunning(false)
    }
  }

  const statusCls = (s) => {
    if (s === 'integre' || s === 'automatise') return 'conforme'
    if (s === 'en_cours') return 'seuil'
    return 'neutral'
  }

  const statusLabel = (s) => ({
    integre: 'Intégré',
    automatise: 'Automatisé',
    en_cours: 'En cours',
    non_integre: 'Non intégré',
  }[s] || s)

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-title">Administration du corpus</div>
          <div className="section-sub">Gestion des sources documentaires et du pipeline d'ingestion</div>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={fetchAll} disabled={loadingStats}>
          {loadingStats ? <span className="spinner dark" /> : <RefreshCw size={13} />}
          Actualiser
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(180px,1fr))', gap: 12, marginBottom: 20 }}>
        {[
          { label: 'Articles valides', value: stats?.valid_articles ?? '—', cls: 'conforme' },
          { label: 'En attente de validation', value: stats?.pending_articles ?? '—', cls: 'vigilance' },
          { label: 'Total articles', value: stats?.total_articles ?? '—', cls: 'seuil' },
          { label: 'Documents indexés', value: stats?.documents?.reduce((s, d) => s + d.n, 0) ?? '—', cls: '' },
        ].map(({ label, value, cls }) => (
          <div className="kpi-card" key={label}>
            <div className="kpi-label">{label}</div>
            <div className={`kpi-value ${cls}`}>{value}</div>
          </div>
        ))}
      </div>

      {stats?.last_bo_check && (
        <div className="alert info" style={{ marginBottom: 16 }}>
          <Clock size={14} style={{ flexShrink: 0 }} />
          <div style={{ fontSize: 12 }}>
            Dernière vérification du Bulletin Officiel :{' '}
            <span className="mono">{new Date(stats.last_bo_check).toLocaleString('fr-MA')}</span>
          </div>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
        <div className="card">
          <div className="card-header">
            <span className="card-title">Pipeline complet</span>
            <Badge cls="neutral">Extract + Ingest</Badge>
          </div>
          <div className="card-body">
            <p style={{ fontSize: 12.5, color: 'var(--ardoise)', lineHeight: 1.6, marginBottom: 16 }}>
              Détecte le CGI de la nouvelle année, télécharge les PDFs, extrait les articles et ingère dans Supabase.
              La validation des articles se fait dans la section Relecture ci-dessous.
            </p>
            <button className="btn btn-primary" onClick={triggerPipeline} disabled={pipelineRunning}>
              {pipelineRunning ? <span className="spinner" /> : <PlayCircle size={13} />}
              Lancer le pipeline
            </button>
            {lastPipelineResult && (
              <div className={`alert ${lastPipelineResult.status === 'ok' ? 'conforme' : 'critique'}`} style={{ marginTop: 12 }}>
                <div className="alert-dot" />
                <div style={{ fontSize: 12 }}>
                  {lastPipelineResult.status === 'ok'
                    ? 'Pipeline terminé avec succès.'
                    : `Erreur — ${lastPipelineResult.error || 'voir les logs'}`}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Veille Bulletin Officiel</span>
            <Badge cls="seuil" dot>Automatisable</Badge>
          </div>
          <div className="card-body">
            <p style={{ fontSize: 12.5, color: 'var(--ardoise)', lineHeight: 1.6, marginBottom: 16 }}>
              Vérifie les nouveaux numéros du BO sur le site du SGG. Télécharge automatiquement si un nouveau numéro est détecté.
              Ne déclenche pas l'extraction — à faire ensuite via le pipeline complet.
            </p>
            <button className="btn btn-secondary" onClick={triggerMonitor} disabled={monitorRunning}>
              {monitorRunning ? <span className="spinner dark" /> : <Radio size={13} />}
              Vérifier maintenant
            </button>
            {lastMonitorResult && (
              <div className={`alert ${lastMonitorResult.status === 'ok' ? 'conforme' : 'critique'}`} style={{ marginTop: 12 }}>
                <div className="alert-dot" />
                <div style={{ fontSize: 12 }}>
                  {lastMonitorResult.found_new_bulletins
                    ? 'Nouveau(x) Bulletin(s) Officiel(s) détecté(s) et téléchargé(s).'
                    : 'Aucune nouveauté détectée depuis la dernière vérification.'}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 20 }}>
        <div className="card-header">
          <span className="card-title">Relecture des articles</span>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <select
              value={articleFilter}
              onChange={(e) => setArticleFilter(e.target.value)}
              style={{ fontSize: 11, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--bordure)' }}
            >
              <option value="a_verifier">En attente</option>
              <option value="valide">Validés</option>
            </select>
            <Badge cls="vigilance">{articlesTotal} article(s)</Badge>
          </div>
        </div>
        <div className="card-body">
          <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
            <button className="btn btn-primary btn-sm" onClick={validateSelected} disabled={!selectedIds.size}>
              <CheckSquare size={13} /> Valider la sélection ({selectedIds.size})
            </button>
            {articleFilter === 'a_verifier' && (
              <button className="btn btn-secondary btn-sm" onClick={validateAllPending} disabled={!articlesTotal}>
                <CheckCircle2 size={13} /> Tout valider
              </button>
            )}
            <button className="btn btn-secondary btn-sm" onClick={rejectSelected} disabled={!selectedIds.size}>
              <Trash2 size={13} /> Supprimer la sélection
            </button>
            <button className="btn btn-secondary btn-sm" onClick={deduplicate}>
              <RefreshCw size={13} /> Nettoyer les doublons
            </button>
            <button className="btn btn-secondary btn-sm" onClick={triggerIngest} disabled={ingestRunning}>
              {ingestRunning ? <span className="spinner dark" /> : <Database size={13} />}
              Ingérer les validés
            </button>
          </div>
          {dedupeResult && (
            <div className="alert conforme" style={{ marginBottom: 12 }}>
              <div className="alert-dot" />
              <div style={{ fontSize: 12 }}>
                {dedupeResult.removed} doublon(s) supprimé(s) — {dedupeResult.remaining} article(s) restant(s).
              </div>
            </div>
          )}
          {loadingArticles ? (
            <div style={{ textAlign: 'center', padding: 24 }}><span className="spinner dark" /></div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: activeArticle ? '1fr 1fr' : '1fr', gap: 16 }}>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--bordure)', textAlign: 'left' }}>
                      <th style={{ padding: '6px 8px', width: 32 }}>
                        <input type="checkbox" checked={articles.length > 0 && selectedIds.size === articles.length} onChange={toggleSelectAll} />
                      </th>
                      {['Référence', 'Source', 'Aperçu'].map((h) => (
                        <th key={h} style={{ padding: '6px 8px', fontWeight: 500, color: 'var(--sourdine)', fontSize: 11 }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {articles.map((a) => (
                      <tr
                        key={a.id}
                        style={{ borderBottom: '1px solid var(--bordure)', cursor: 'pointer', background: activeArticle?.id === a.id ? 'var(--surface-2, #f8f9fa)' : 'transparent' }}
                        onClick={() => openArticle(a.id)}
                      >
                        <td style={{ padding: '6px 8px' }} onClick={(e) => e.stopPropagation()}>
                          <input type="checkbox" checked={selectedIds.has(a.id)} onChange={() => toggleSelect(a.id)} />
                        </td>
                        <td style={{ padding: '6px 8px', fontFamily: 'var(--font-mono)', fontSize: 11, whiteSpace: 'nowrap' }}>{a.reference}</td>
                        <td style={{ padding: '6px 8px', color: 'var(--ardoise)', fontSize: 11, maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.source_label}</td>
                        <td style={{ padding: '6px 8px', color: 'var(--sourdine)', fontSize: 11, maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.apercu}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {articlesPages > 1 && (
                  <div style={{ display: 'flex', justifyContent: 'center', gap: 12, marginTop: 12, alignItems: 'center' }}>
                    <button className="btn btn-secondary btn-sm" disabled={articlesPage <= 1} onClick={() => fetchArticles(articlesPage - 1, articleFilter)}>
                      <ChevronLeft size={13} />
                    </button>
                    <span style={{ fontSize: 12, color: 'var(--sourdine)' }}>Page {articlesPage} / {articlesPages}</span>
                    <button className="btn btn-secondary btn-sm" disabled={articlesPage >= articlesPages} onClick={() => fetchArticles(articlesPage + 1, articleFilter)}>
                      <ChevronRight size={13} />
                    </button>
                  </div>
                )}
              </div>
              {activeArticle && (
                <div style={{ border: '1px solid var(--bordure)', borderRadius: 8, padding: 16, maxHeight: 480, overflowY: 'auto' }}>
                  <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>{activeArticle.reference}</div>
                  <div style={{ fontSize: 11, color: 'var(--sourdine)', marginBottom: 12 }}>{activeArticle.source_label}</div>
                  <div style={{ fontSize: 12.5, lineHeight: 1.7, color: 'var(--encre)', whiteSpace: 'pre-wrap' }}>{activeArticle.texte}</div>
                  <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
                    {activeArticle.statut === 'a_verifier' && (
                      <button className="btn btn-primary btn-sm" onClick={async () => {
                        await fetch(`${API_URL}/admin/articles/validate`, {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ ids: [activeArticle.id] }),
                        })
                        setActiveArticle(null)
                        fetchArticles(articlesPage, articleFilter)
                        fetchAll()
                      }}>
                        <CheckCircle2 size={13} /> Valider cet article
                      </button>
                    )}
                    <button className="btn btn-secondary btn-sm" onClick={() => setActiveArticle(null)}>Fermer</button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {log.length > 0 && (
        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-header">
            <span className="card-title">Journal d'exécution</span>
            <span style={{ fontSize: 11, color: 'var(--sourdine)' }}>Session courante</span>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--bordure)', textAlign: 'left' }}>
                  {['Horodatage', 'Déclencheur', 'Statut'].map((h) => (
                    <th key={h} style={{ padding: '8px 16px', fontWeight: 500, color: 'var(--sourdine)', fontSize: 11 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {log.map((entry, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--bordure)' }}>
                    <td style={{ padding: '8px 16px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ardoise)' }}>
                      {new Date(entry.ts + 'Z').toLocaleString('fr-MA')}
                    </td>
                    <td style={{ padding: '8px 16px', color: 'var(--ardoise)' }}>
                      {entry.trigger === 'manual_full' ? 'Pipeline complet' : entry.trigger === 'monitor_bo' ? 'Veille BO' : entry.trigger}
                    </td>
                    <td style={{ padding: '8px 16px' }}>
                      <Badge cls={entry.status === 'ok' ? 'conforme' : 'critique'}>
                        {entry.status}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: 20 }}>
        <div className="card-header">
          <span className="card-title">Méthodologie & Calcul des Scores Fiscaux</span>
          <Badge cls="seuil">Spécification Nisab 2026</Badge>
        </div>
        <div className="card-body">
          <p style={{ fontSize: 12.5, color: 'var(--ardoise)', lineHeight: 1.6, marginBottom: 16 }}>
            Le moteur Nisab qualifie la conformité fiscale selon 3 indicateurs synthétiques et une évaluation financière de l'exposition au redressement :
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 14 }}>
            <div style={{ background: 'var(--toile)', border: '1px solid var(--bordure)', borderRadius: 6, padding: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--seuil)', textTransform: 'uppercase', marginBottom: 6 }}>
                1. Score de Conformité Globale
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--encre)', fontWeight: 600, marginBottom: 6 }}>
                100 − (Nb Anomalies × 8)
              </div>
              <div style={{ fontSize: 12, color: 'var(--ardoise)', lineHeight: 1.5 }}>
                Note sur 100 avec <strong>Seuil de conformité à 70</strong>. Chaque anomalie détectée soustrait 8 points au capital initial de 100.
              </div>
            </div>
            <div style={{ background: 'var(--toile)', border: '1px solid var(--bordure)', borderRadius: 6, padding: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--seuil)', textTransform: 'uppercase', marginBottom: 6 }}>
                2. Score de Préparation à l'Audit
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--encre)', fontWeight: 600, marginBottom: 6 }}>
                max(0, Score Conformité − 8)
              </div>
              <div style={{ fontSize: 12, color: 'var(--ardoise)', lineHeight: 1.5 }}>
                Évalue la capacité de l'entreprise à affronter immédiatement un contrôle de la DGI (Seuil visé : <strong>75/100</strong>).
              </div>
            </div>
            <div style={{ background: 'var(--toile)', border: '1px solid var(--bordure)', borderRadius: 6, padding: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--seuil)', textTransform: 'uppercase', marginBottom: 6 }}>
                3. Score de Risque Fiscal
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--encre)', fontWeight: 600, marginBottom: 6 }}>
                min(100, Nb Anomalies × 12)
              </div>
              <div style={{ fontSize: 12, color: 'var(--ardoise)', lineHeight: 1.5 }}>
                Mesure l'intensité du risque. Un score élevé (&gt; 60) signale un danger immédiat de redressement fiscal lourd.
              </div>
            </div>
            <div style={{ background: 'var(--toile)', border: '1px solid var(--bordure)', borderRadius: 6, padding: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--critique)', textTransform: 'uppercase', marginBottom: 6 }}>
                4. Exposition Financière (MAD)
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--critique)', fontWeight: 700, marginBottom: 6 }}>
                ∑ (Risque TVA + Réintégrations + Pénalités)
              </div>
              <div style={{ fontSize: 12, color: 'var(--ardoise)', lineHeight: 1.5 }}>
                Somme exacte des réintégrations d'impôt et de TVA indûment déduite selon les articles du CGI 2026 (Art. 193, 106-IV, 10-I-F).
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Sources documentaires recommandées</span>
          <span style={{ fontSize: 11, color: 'var(--sourdine)' }}>{sources.length} sources</span>
        </div>
        <div className="card-body" style={{ padding: 0 }}>
          {sources.map((src, i) => (
            <div key={src.id} style={{ padding: '14px 20px', borderBottom: i < sources.length - 1 ? '1px solid var(--bordure)' : 'none', display: 'flex', alignItems: 'flex-start', gap: 14 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--encre)' }}>{src.label}</span>
                  <Badge cls={statusCls(src.status)} dot>{statusLabel(src.status)}</Badge>
                  {src.priority === 'haute' && <Badge cls="critique">Priorité haute</Badge>}
                  {src.priority === 'moyenne' && <Badge cls="vigilance">Priorité moyenne</Badge>}
                </div>
                <div style={{ fontSize: 12, color: 'var(--ardoise)', lineHeight: 1.55, marginBottom: 4 }}>{src.description}</div>
                <div style={{ display: 'flex', gap: 16 }}>
                  <span style={{ fontSize: 11, color: 'var(--sourdine)' }}>
                    <span className="mono" style={{ color: 'var(--seuil)', fontSize: 10 }}>{src.type}</span>
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--sourdine)' }}>
                    Mise à jour : {src.update_frequency}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
