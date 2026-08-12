import { useCallback, useEffect, useState } from 'react'
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'
import Badge from '../components/Badge'
import DossierPicker from '../components/DossierPicker'
import { apiFetch } from '../config/api'
import { useDossier } from '../context/DossierContext'
import { badgeTones, colors, radius, spacing } from '../theme'

// Même mapping que URGENCY_CLS dans frontend/src/pages/CabinetOverviewPage.jsx:8
const URGENCY_TONE = { critique: 'critique', urgent: 'vigilance', normal: 'seuil', planifié: 'conforme' }

export default function EcheancesScreen() {
  const { activeDossier } = useDossier()
  const [events, setEvents] = useState(null) // null = pas encore chargé
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(async () => {
    if (!activeDossier) return
    const res = await apiFetch(`/dossiers/${activeDossier.id}/calendar/events`)
    const data = res.ok ? await res.json() : { events: [] }
    setEvents(data.events || [])
  }, [activeDossier])

  useEffect(() => { setEvents(null); load() }, [load])

  const onRefresh = useCallback(async () => {
    setRefreshing(true)
    await load()
    setRefreshing(false)
  }, [load])

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <Text style={styles.title}>Échéances</Text>
        {activeDossier && <Text style={styles.subtitle}>{activeDossier.raison_sociale}</Text>}
      </View>
      <DossierPicker />

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.seuil} />}
      >
        {!activeDossier ? (
          <Text style={styles.muted}>Aucun dossier rattaché.</Text>
        ) : events === null ? (
          <Text style={styles.muted}>Chargement…</Text>
        ) : events.length === 0 ? (
          <Text style={styles.muted}>Aucune échéance à venir.</Text>
        ) : (
          events.map((e, i) => (
            <View key={`${e.date}-${i}`} style={styles.row}>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowTitle}>{e.title}</Text>
                <Text style={styles.rowDate}>
                  {new Date(e.date).toLocaleDateString('fr-MA', { day: 'numeric', month: 'long', year: 'numeric' })}
                </Text>
              </View>
              <Badge tone={badgeTones[URGENCY_TONE[e.urgency]] || badgeTones.neutral}>{e.category}</Badge>
            </View>
          ))
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
  row: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.md,
    backgroundColor: colors.surface, borderRadius: radius.card, borderWidth: 1, borderColor: colors.bordure,
    padding: spacing.md, marginBottom: spacing.sm,
  },
  rowTitle: { fontSize: 13, fontWeight: '600', color: colors.encre },
  rowDate: { fontSize: 11.5, color: colors.sourdine, marginTop: 2 },
})
