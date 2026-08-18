import { ScrollView, StyleSheet, Text, TouchableOpacity } from 'react-native'
import { useDossier } from '../context/DossierContext'
import { colors, fonts, spacing } from '../theme'

/**
 * Sélecteur de dossier — nécessaire uniquement pour les écrans Échéances et
 * Alertes critiques, qui portent sur UN dossier (contrairement à Feux
 * tricolores, qui liste tous les dossiers d'un coup comme DirigeantShell
 * côté web). Un dirigeant n'a en général qu'un seul dossier rattaché ; ça
 * reste un défilement horizontal de puces plutôt qu'un vrai <Picker> pour
 * ne pas ajouter de dépendance native pour le cas à 1 dossier.
 */
export default function DossierPicker() {
  const { dossiers, activeDossier, setActiveDossier } = useDossier()

  if (dossiers.length <= 1) return null

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      style={styles.row}
      contentContainerStyle={styles.rowContent}
    >
      {dossiers.map((d) => {
        const active = d.id === activeDossier?.id
        return (
          <TouchableOpacity
            key={d.id}
            style={[styles.chip, active && styles.chipActive]}
            onPress={() => setActiveDossier(d)}
          >
            <Text style={[styles.chipText, active && styles.chipTextActive]}>{d.raison_sociale}</Text>
          </TouchableOpacity>
        )
      })}
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  row: { flexGrow: 0, marginBottom: spacing.md },
  rowContent: { gap: spacing.sm, paddingHorizontal: spacing.lg },
  // Carré, pas pilule — même choix que .filter-chip côté web (App.css:493-506,
  // border-radius:0) : la forme arrondie pleine est un motif que Direction D
  // a explicitement banni, pas seulement sur Badge.
  chip: {
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderWidth: 1, borderColor: colors.bordure, backgroundColor: colors.surface,
  },
  chipActive: { backgroundColor: colors.seuil, borderColor: colors.seuil },
  chipText: { fontFamily: fonts.sansMedium, fontSize: 12.5, color: colors.ardoise },
  chipTextActive: { color: colors.accentInk },
})
