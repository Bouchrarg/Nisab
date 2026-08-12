import { useState } from 'react'
import { apiFetch } from '../../config/api'
import { reflowText } from '../../utils/text'

// reference_cgi arrive formaté ("Article 102 du CGI") alors que rag_sources
// contient la forme brute retournée par le RAG ("Article 102") : une
// comparaison stricte de chaînes ne matche jamais, d'où le doublon visuel.
// On normalise sur le numéro d'article seul avant de comparer.
function normalizeArticleRef(ref) {
  if (!ref) return ''
  const match = ref.match(/article\s+[\w-]+(\s+(bis|ter|quater|quinquies|sexies))?/i)
  return (match ? match[0] : ref).toLowerCase().trim()
}

/**
 * Pastilles de citation dépliables, avec lecture du texte de loi.
 *
 * Extrait de FindingCard pour être partagé par les trois endroits du produit
 * où une sortie IA doit pouvoir être remontée à sa source : l'audit, les
 * propositions de correction, la veille. Ce n'est pas une factorisation de
 * confort — c'est la garantie que « cliquer sur un article affiche son texte »
 * se comporte pareil partout, y compris quand l'article a disparu du corpus.
 *
 * `principale` est mise en avant (couleur, taille) : c'est le fondement retenu.
 * `secondaires` sont les autres articles retrouvés par le RAG, dédoublonnés
 * contre la principale.
 *
 * `source` (optionnel) : le millésime du corpus qui a réellement produit ces
 * citations, ex. « Code General des Impots 2024 (version 2024-01-01) ». Le
 * titre par défaut annonçait « CGI 2026 » EN DUR : un audit lancé contre le
 * CGI 2024 (sélecteur de source, AuditPage) affichait donc un millésime faux
 * sous chaque alerte, alors que la base, elle, portait le bon
 * (CitationRisque.version_corpus). Non fourni = aucune source affichée, jamais
 * une source supposée — c'est la même règle que partout ailleurs dans le
 * produit : ne rien affirmer qu'on ne puisse rattacher.
 */
export default function CitationPills({
  principale,
  secondaires = [],
  titre = "Fondement légal — cliquez pour lire l'article",
  source = null,
}) {
  const [activeRef, setActiveRef] = useState(null)
  const [texte, setTexte] = useState(null)
  const [loading, setLoading] = useState(false)
  const [erreur, setErreur] = useState(null)

  const autres = (secondaires || []).filter(
    (s) => normalizeArticleRef(s) !== normalizeArticleRef(principale)
  )

  if (!principale && autres.length === 0) return null

  const toggle = async (ref) => {
    if (activeRef === ref) {
      setActiveRef(null)
      return
    }
    setActiveRef(ref)
    setTexte(null)
    setErreur(null)
    setLoading(true)
    try {
      const res = await apiFetch(`/articles/by-reference?reference=${encodeURIComponent(ref)}`)
      if (!res.ok) {
        // Un article absent du corpus courant n'est pas une erreur technique :
        // le corpus est versionné, un article a pu être abrogé depuis l'audit.
        setErreur('Article non retrouvé dans le corpus actuel, vérification manuelle recommandée.')
      } else {
        setTexte((await res.json()).texte_complet)
      }
    } catch {
      setErreur('Erreur lors de la récupération du texte de loi.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--sourdine)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          {titre}
        </div>
        {source && (
          <span
            title="Source du corpus contre laquelle cette alerte a été produite"
            style={{
              fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--ardoise)',
              background: 'var(--toile)', border: '1px solid var(--bordure)',
              borderRadius: 4, padding: '1px 6px',
            }}
          >
            {source}
          </span>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {principale && (
          <button
            onClick={() => toggle(principale)}
            style={{
              fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--seuil)',
              background: activeRef === principale
                ? 'color-mix(in srgb, var(--seuil) 20%, transparent)'
                : 'color-mix(in srgb, var(--seuil) 10%, transparent)',
              border: '1px solid color-mix(in srgb, var(--seuil) 25%, transparent)',
              borderRadius: 4, padding: '2px 8px', fontWeight: 600, cursor: 'pointer',
            }}>{principale}</button>
        )}
        {autres.map((s, i) => (
          <button
            key={i}
            onClick={() => toggle(s)}
            style={{
              fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--ardoise)',
              background: activeRef === s ? 'var(--bordure)' : 'var(--toile)',
              border: '1px solid var(--bordure)',
              borderRadius: 4, padding: '2px 6px', cursor: 'pointer',
            }}>{s}</button>
        ))}
      </div>
      {activeRef && (
        <div className="law-article-text" style={{ marginTop: 8, borderRadius: 6, border: '1px solid var(--bordure)' }}>
          {loading && 'Chargement de l\'article…'}
          {!loading && erreur && erreur}
          {!loading && !erreur && reflowText(texte)}
        </div>
      )}
    </div>
  )
}
