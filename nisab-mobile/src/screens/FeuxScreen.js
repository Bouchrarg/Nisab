import { useCallback, useEffect, useState } from 'react'
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'
import Badge from '../components/Badge'
import { apiFetch } from '../config/api'
import { useDossier } from '../context/DossierContext'
import { colors, feuColors, radius, spacing } from '../theme'

// Port direct de feuTricolore() dans frontend/src/pages/DirigeantShell.jsx:23-29
// — même 4 états, même raison d'être : "gris" (indéterminé : pas de donnée,
// jamais audité, erreur) ne doit JAMAIS s'afficher comme "vert" (conforme).
// Un {rouge:0, orange:0} ne prouve rien si aucun audit n'a jamais tourné.
function feuTricolore(summary) {
  if (!summary || summary.status === 'no_data') return 'gris'
  if (summary.audit_status === 'jamais_lance' || summary.audit_status === 'error') return 'gris'
  if ((summary.risks?.rouge || 0) > 0) return 'rouge'
  if ((summary.risks?.orange || 0) > 0) return 'orange'
  return 'vert'
}

const FEU_LABEL = { rouge: 'Attention requise', orange: 'À surveiller', vert: 'Situation saine', gris: 'Indéterminé' }

function DossierFeuCard({ dossier }) {
  const [summary, setSummary] = useState(null)
  const [nextEcheance, setNextEcheance] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const [summaryRes, calendarRes] = await Promise.all([
          apiFetch(`/dossiers/${dossier.id}/dashboard/summary`),
          apiFetch(`/dossiers/${dossier.id}/calendar/events`),
        ])
        if (cancelled) return
        setSummary(summaryRes.ok ? await summaryRes.json() : null)
        const cal = calendarRes.ok ? await calendarRes.json() : { events: [] }
        setNextEcheance((cal.events || [])[0] || null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [dossier.id])

  const feu = feuTricolore(summary)
  const tone = feuColors[feu]

  return (
    <View style={styles.card}>
      <View style={styles.cardHead}>
        <View style={{ flex: 1 }}>
          <Text style={styles.dossierName}>{dossier.raison_sociale}</Text>
          <Text style={styles.dossierSector}>{dossier.secteur_activite || 'Secteur non renseigné'}</Text>
        </View>
        <Badge tone={tone}>{FEU_LABEL[feu]}</Badge>
      </View>

      {loading ? (
        <Text style={styles.muted}>Chargement…</Text>
      ) : summary?.status === 'no_data' ? (
        <Text style={styles.muted}>Aucune donnée comptable chargée pour ce dossier — contactez votre cabinet.</Text>
      ) : summary?.audit_status === 'jamais_lance' ? (
        <Text style={styles.muted}>
          Les données comptables sont chargées mais l'analyse fiscale n'a pas encore été réalisée — contactez votre
          cabinet pour la lancer.
        </Text>
      ) : (
        <>
          <Text style={styles.summary}>{summary?.executive_summary || 'Analyse indisponible pour le moment.'}</Text>
          {nextEcheance && (
            <View style={styles.nextEcheance}>
              <Text style={styles.nextEcheanceLabel}>Prochaine échéance</Text>
              <Text style={styles.nextEcheanceValue}>
                {nextEcheance.title} — {new Date(nextEcheance.date).toLocaleDateString('fr-MA', { day: 'numeric', month: 'long', year: 'numeric' })}
              </Text>
            </View>
          )}
        </>
      )}
    </View>
  )
}

export default function FeuxScreen() {
  const { dossiers, loading, refreshDossiers } = useDossier()
  const [refreshing, setRefreshing] = useState(false)

  const onRefresh = useCallback(async () => {
    setRefreshing(true)
    await refreshDossiers()
    setRefreshing(false)
  }, [refreshDossiers])

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.seuil} />}
    >
      <Text style={styles.title}>Votre situation fiscale</Text>
      <Text style={styles.subtitle}>
        Vue d'ensemble simplifiée — pour le détail, votre cabinet comptable reste votre interlocuteur.
      </Text>

      {loading ? (
        <Text style={styles.muted}>Chargement de vos dossiers…</Text>
      ) : dossiers.length === 0 ? (
        <View style={styles.empty}>
          <Text style={styles.emptyTitle}>Aucun dossier ne vous a encore été rattaché</Text>
          <Text style={styles.muted}>Contactez votre cabinet comptable pour qu'il vous donne accès à votre dossier.</Text>
        </View>
      ) : (
        dossiers.map((d) => <DossierFeuCard key={d.id} dossier={d} />)
      )}
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.toile },
  content: { padding: spacing.lg, paddingBottom: spacing.xxl },
  title: { fontSize: 19, fontWeight: '700', color: colors.encre },
  subtitle: { fontSize: 13, color: colors.sourdine, marginTop: 2, marginBottom: spacing.lg },
  muted: { fontSize: 12.5, color: colors.sourdine },
  empty: { backgroundColor: colors.surface, borderRadius: radius.card, borderWidth: 1, borderColor: colors.bordure, padding: spacing.xl, gap: spacing.xs },
  emptyTitle: { fontSize: 14, fontWeight: '600', color: colors.encre },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.card, borderWidth: 1, borderColor: colors.bordure,
    padding: spacing.lg, marginBottom: spacing.md,
  },
  cardHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: spacing.sm, marginBottom: spacing.md },
  dossierName: { fontSize: 15, fontWeight: '700', color: colors.encre },
  dossierSector: { fontSize: 11.5, color: colors.sourdine, marginTop: 2 },
  summary: { fontSize: 13, color: colors.ardoise, lineHeight: 20 },
  nextEcheance: { borderTopWidth: 1, borderTopColor: colors.bordureDiscrete, marginTop: spacing.md, paddingTop: spacing.sm },
  nextEcheanceLabel: { fontSize: 10.5, color: colors.sourdine, textTransform: 'uppercase' },
  nextEcheanceValue: { fontSize: 12.5, color: colors.ardoise, marginTop: 2 },
})
