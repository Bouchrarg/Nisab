import { useState } from 'react'
import { Check } from 'lucide-react'
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
 * Direction D : trois textures, pas deux. `principale` = sourcée (bordure
 * pleine + coche, c'est le fondement retenu). `secondaires` = étiquette
 * neutre (autres candidats remontés par le RAG). La troisième texture — non
 * vérifié, bordure pointillée + italique — ne peut PAS être connue à
 * l'avance : on ne sait si un article existe encore dans le corpus qu'après
 * l'avoir cherché (le corpus est versionné, un article a pu être abrogé
 * depuis l'audit). Elle s'applique donc à la pastille cliquée UNE FOIS que
 * la recherche a échoué, pas par anticipation.
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

  // Non vérifié seulement pour la pastille qu'on vient de chercher et qui
  // n'a rien donné — pas pour les autres, dont on ne sait encore rien.
  const nonVerifie = (ref) => activeRef === ref && !loading && erreur

  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--sourdine)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          {titre}
        </div>
        {source && (
          <span className="citation-source-tag" title="Source du corpus contre laquelle cette alerte a été produite">
            {source}
          </span>
        )}
      </div>
      <div className="citations-row">
        {principale && (
          <button
            onClick={() => toggle(principale)}
            className={`citation-pill ${nonVerifie(principale) ? 'is-unverified' : 'is-primary'}`}
          >
            {!nonVerifie(principale) && <Check size={11} />}
            {principale}
          </button>
        )}
        {autres.map((s, i) => (
          <button
            key={i}
            onClick={() => toggle(s)}
            className={`citation-pill ${nonVerifie(s) ? 'is-unverified' : 'is-secondary'}`}
          >
            {s}
          </button>
        ))}
      </div>
      {activeRef && (
        <div className={`law-article-text${erreur && !loading ? ' is-unverified' : ''}`} style={{ marginTop: 8 }}>
          {loading && 'Chargement de l\'article…'}
          {!loading && erreur && erreur}
          {!loading && !erreur && reflowText(texte)}
        </div>
      )}
    </div>
  )
}
