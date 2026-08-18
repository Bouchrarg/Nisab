import { useCallback, useEffect, useState } from 'react'
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'
import Badge from '../components/Badge'
import DossierPicker from '../components/DossierPicker'
import { apiFetch } from '../config/api'
import { useDossier } from '../context/DossierContext'
import { badgeTones, colors, fonts, radius, spacing } from '../theme'

// Même mapping que URGENCY_CLS dans frontend/src/pages/CabinetOverviewPage.jsx:8
const URGENCY_TONE = { critique: 'critique', urgent: 'vigilance', normal: 'seuil', planifié: 'conforme' }

// Jour + mois seuls (pas d'année) — même gabarit que .list-date côté web
// (frontend/src/components/calendar/CalendarEvent.jsx), un repère net plutôt
// qu'une date en toutes lettres noyée dans le corps de la ligne.
function dateParts(iso) {
  const d = new Date(iso)
  const day = d.toLocaleDateString('fr-MA', { day: '2-digit' })
  const month = d.toLocaleDateString('fr-MA', { month: 'short' }).replace(/\.$/, '')
  return { day, month }
}

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
          <View style={styles.list}>
            {events.map((e, i) => {
              const { day, month } = dateParts(e.date)
              const urgent = e.urgency === 'critique' || e.urgency === 'urgent'
              return (
                <View key={`${e.date}-${i}`} style={[styles.row, i !== events.length - 1 && styles.rowBorder]}>
                  <View style={[styles.dateBox, urgent && styles.dateBoxUrgent]}>
                    <Text style={[styles.dateDay, urgent && styles.dateDayUrgent]}>{day}</Text>
                    <Text style={styles.dateMonth}>{month}</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowTitle} numberOfLines={2}>{e.title}</Text>
                    {e.description ? <Text style={styles.rowSub} numberOfLines={2}>{e.description}</Text> : null}
                  </View>
                  <Badge tone={badgeTones[URGENCY_TONE[e.urgency]] || badgeTones.neutral} small>{e.category}</Badge>
                </View>
              )
            })}
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
  list: {
    backgroundColor: colors.surface, borderRadius: radius.card, borderWidth: 1, borderColor: colors.bordure,
    overflow: 'hidden', marginBottom: spacing.md,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.md },
  rowBorder: { borderBottomWidth: 1, borderBottomColor: colors.bordure },
  dateBox: {
    minWidth: 38, alignItems: 'center', paddingVertical: 4, paddingHorizontal: 3,
    backgroundColor: colors.surface2, borderWidth: 1, borderColor: colors.bordure, borderRadius: radius.sm,
  },
  dateBoxUrgent: { borderColor: colors.critique },
  dateDay: { fontFamily: fonts.monoSemiBold, fontSize: 14, color: colors.encre, lineHeight: 16 },
  dateDayUrgent: { color: colors.critique },
  dateMonth: { fontFamily: fonts.sans, fontSize: 9, color: colors.sourdine, textTransform: 'uppercase', letterSpacing: 0.4 },
  rowTitle: { fontFamily: fonts.sansBold, fontSize: 13, color: colors.encre, lineHeight: 17 },
  rowSub: { fontFamily: fonts.sans, fontSize: 11, color: colors.sourdine, marginTop: 1 },
})
