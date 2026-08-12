import { useCallback, useEffect, useState } from 'react'
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'
import DossierPicker from '../components/DossierPicker'
import { apiFetch } from '../config/api'
import { useDossier } from '../context/DossierContext'
import { colors, radius, spacing } from '../theme'

// Même règle qu'ailleurs dans le produit (FindingCard.jsx) : "non_calculable"
// reste visible, jamais silencieusement absent — une règle a explicitement
// conclu qu'elle ne pouvait rien affirmer, ce n'est pas un vide.
const LABEL_CATEGORIE_MONTANT = {
  calculable: 'Exposition calculée',
  calculable_hypothese: 'Exposition calculée (sous hypothèse)',
  non_calculable: 'Montant non chiffrable automatiquement',
}

function AlerteCard({ f }) {
  const montantChiffre = f.categorie_montant !== 'non_calculable' && f.amount_risk > 0
  return (
    <View style={styles.card}>
      <View style={styles.cardBar} />
      <View style={styles.cardBody}>
        <Text style={styles.cardTitle}>{f.title || 'Comptabilité non conforme'}</Text>

        {montantChiffre ? (
          <Text style={styles.amount}>
            {f.categorie_montant === 'calculable_hypothese' ? '≈ ' : ''}
            {Number(f.amount_risk).toLocaleString('fr-MA')} DH
            <Text style={styles.amountLabel}>  {LABEL_CATEGORIE_MONTANT[f.categorie_montant]}</Text>
          </Text>
        ) : (
          <Text style={styles.amountNone}>{LABEL_CATEGORIE_MONTANT.non_calculable}</Text>
        )}

        {f.description ? <Text style={styles.description}>{f.description}</Text> : null}
        {f.montant_detail ? <Text style={styles.detail}>{f.montant_detail}</Text> : null}

        {/* Zéro affirmation sans source, jusque sur ce shell lecture seule —
            même exigence que CitationPills côté web (frontend/src/components/
            audit/CitationPills.jsx), en version simple lecture. */}
        {f.reference_cgi ? (
          <View style={styles.citation}>
            <Text style={styles.citationText}>{f.reference_cgi}</Text>
          </View>
        ) : null}
      </View>
    </View>
  )
}

export default function AlertesScreen() {
  const { activeDossier } = useDossier()
  const [result, setResult] = useState(null) // null = pas encore chargé
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(async () => {
    if (!activeDossier) return
    const res = await apiFetch(`/dossiers/${activeDossier.id}/audit/resultat`)
    setResult(res.ok ? await res.json() : { findings: [], audit_status: 'error' })
  }, [activeDossier])

  useEffect(() => { setResult(null); load() }, [load])

  const onRefresh = useCallback(async () => {
    setRefreshing(true)
    await load()
    setRefreshing(false)
  }, [load])

  const critiques = (result?.findings || []).filter((f) => f.severity === 'rouge')

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <Text style={styles.title}>Alertes critiques</Text>
        {activeDossier && <Text style={styles.subtitle}>{activeDossier.raison_sociale}</Text>}
      </View>
      <DossierPicker />

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.seuil} />}
      >
        {!activeDossier ? (
          <Text style={styles.muted}>Aucun dossier rattaché.</Text>
        ) : result === null ? (
          <Text style={styles.muted}>Chargement…</Text>
        ) : result.audit_status === 'jamais_lance' ? (
          <Text style={styles.muted}>
            Aucune analyse n'a encore été lancée sur ce dossier — contactez votre cabinet.
          </Text>
        ) : critiques.length === 0 ? (
          <Text style={styles.muted}>Aucune alerte critique active sur ce dossier.</Text>
        ) : (
          critiques.map((f) => <AlerteCard key={f.id} f={f} />)
        )}
      </ScrollView>
    </View>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.toile },
  header: { paddingHorizontal: spacing.lg, paddingTop: spacing.lg },
  title: { fontSize: 19, fontWeight: '700', color: colors.encre },
  subtitle: { fontSize: 12.5, color: colors.sourdine, marginTop: 2, marginBottom: spacing.md },
  content: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xxl },
  muted: { fontSize: 12.5, color: colors.sourdine, paddingTop: spacing.sm },
  card: {
    flexDirection: 'row', backgroundColor: colors.surface, borderRadius: radius.card,
    borderWidth: 1, borderColor: colors.bordure, marginBottom: spacing.md, overflow: 'hidden',
  },
  cardBar: { width: 3, backgroundColor: colors.critique },
  cardBody: { flex: 1, padding: spacing.md, gap: 6 },
  cardTitle: { fontSize: 13.5, fontWeight: '700', color: colors.encre },
  amount: { fontSize: 13, fontWeight: '700', color: colors.critique },
  amountLabel: { fontSize: 11, fontWeight: '400', color: colors.sourdine },
  amountNone: { fontSize: 11.5, color: colors.sourdine, fontWeight: '500' },
  description: { fontSize: 12, color: colors.ardoise, lineHeight: 18 },
  detail: { fontSize: 11, color: colors.sourdine, lineHeight: 16 },
  citation: {
    alignSelf: 'flex-start', backgroundColor: colors.seuilSoft, borderRadius: radius.sm,
    paddingHorizontal: spacing.sm, paddingVertical: 4, marginTop: 2,
  },
  citationText: { fontSize: 11, fontWeight: '600', color: colors.seuil },
})
