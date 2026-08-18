import { useCallback, useEffect, useState } from 'react'
import { Platform, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'
import Badge from '../components/Badge'
import DossierPicker from '../components/DossierPicker'
import { apiFetch } from '../config/api'
import { useDossier } from '../context/DossierContext'
import { badgeTones, colors, fonts, radius, spacing } from '../theme'

const LABEL_CATEGORIE_MONTANT = {
  calculable: 'Exposition calculée',
  calculable_hypothese: 'Exposition calculée (sous hypothèse)',
  non_calculable: 'Montant non chiffrable automatiquement',
}

// Équivalent RN de FindingCard (frontend/src/components/audit/FindingCard.jsx)
// en lecture seule. Direction D a retiré la réglette de couleur verticale
// ("ça fait IA") : la sévérité passe uniquement par le Badge carré, jamais
// par un bandeau. Toutes les lignes filtrées ici sont severity==='rouge',
// donc toujours "Critique" — même simplification que le filtre côté écran.
function AlerteCard({ f, isLast }) {
  const montantChiffre = f.categorie_montant !== 'non_calculable' && f.amount_risk > 0
  return (
    <View style={[styles.row, !isLast && styles.rowBorder]}>
      <View style={styles.rowHead}>
        <Badge tone={badgeTones.critique}>Critique</Badge>
        <Text style={styles.cardTitle} numberOfLines={1}>{f.title || 'Comptabilité non conforme'}</Text>
      </View>

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
          même exigence que CitationPills côté web. Texture "sourcé" du
          Direction D : bordure pleine + mono, jamais un fond plein coloré
          (frontend/src/App.css:1037-1041, .citation-pill.is-primary). */}
      {f.reference_cgi ? (
        <View style={styles.citation}>
          <Text style={styles.citationText}>{f.reference_cgi}</Text>
        </View>
      ) : null}
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
          <View style={styles.list}>
            {critiques.map((f, i) => <AlerteCard key={f.id} f={f} isLast={i === critiques.length - 1} />)}
          </View>
        )}
      </ScrollView>
    </View>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.toile },
  header: { paddingHorizontal: spacing.lg, paddingTop: spacing.lg },
  title: { fontFamily: fonts.display, fontSize: 20, color: colors.encre },
  subtitle: { fontFamily: fonts.sans, fontSize: 12.5, color: colors.sourdine, marginTop: 2, marginBottom: spacing.md },
  content: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xxl },
  muted: { fontFamily: fonts.sans, fontSize: 12.5, color: colors.sourdine, paddingTop: spacing.sm },
  // Ombre réservée sur la LISTE entière (une seule entité qu'on consulte),
  // pas par ligne — même règle que .findings-list, cf. App.css:518-531.
  list: {
    backgroundColor: colors.surface, borderRadius: radius.card, borderWidth: 1, borderColor: colors.bordure,
    overflow: 'hidden', marginBottom: spacing.md,
    ...Platform.select({
      ios: { shadowColor: '#1e0f0a', shadowOpacity: 0.14, shadowRadius: 10, shadowOffset: { width: 0, height: 6 } },
      android: { elevation: 3 },
    }),
  },
  row: { padding: spacing.md, gap: 5 },
  rowBorder: { borderBottomWidth: 1, borderBottomColor: colors.bordure },
  rowHead: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: 2 },
  cardTitle: { flex: 1, fontFamily: fonts.sansBold, fontSize: 13.5, color: colors.encre },
  amount: { fontFamily: fonts.monoSemiBold, fontSize: 12, color: colors.critique },
  amountLabel: { fontFamily: fonts.sans, fontSize: 11, color: colors.sourdine },
  amountNone: { fontFamily: fonts.sansMedium, fontSize: 11.5, color: colors.sourdine },
  description: { fontFamily: fonts.sans, fontSize: 12, color: colors.ardoise, lineHeight: 18 },
  detail: { fontFamily: fonts.sans, fontSize: 11, color: colors.sourdine, lineHeight: 16 },
  citation: {
    alignSelf: 'flex-start', borderWidth: 1, borderColor: colors.seuil,
    paddingHorizontal: spacing.sm, paddingVertical: 4, marginTop: 2,
  },
  citationText: { fontFamily: fonts.monoSemiBold, fontSize: 11, color: colors.seuil },
})
