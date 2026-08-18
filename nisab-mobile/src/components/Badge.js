import { StyleSheet, Text, View } from 'react-native'
import { colors, fonts } from '../theme'

// Équivalent RN de frontend/src/components/ui/Badge.jsx — Direction D :
// carré de statut plein + texte toujours en encre neutre, plus jamais une
// pilule colorée (motif jugé "trop IA"). Seul le carré porte la couleur du
// statut (`tone.fg`), le texte reste neutre : on ne branche jamais tone.fg
// sur styles.text.color, même par commodité.
// `small` : variante pour un badge qui n'est qu'une précision secondaire
// dans une ligne (catégorie d'échéance à côté d'un titre qui doit dominer),
// pas le signal principal — cf. .badge-sm dans App.css.
export default function Badge({ tone, children, small = false }) {
  return (
    <View style={styles.badge}>
      <View style={[styles.dot, small && styles.dotSmall, { backgroundColor: tone.fg }]} />
      <Text style={[styles.text, small && styles.textSmall]}>{children}</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  badge: { flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'flex-start' },
  dot: { width: 10, height: 10 },
  dotSmall: { width: 7, height: 7 },
  text: { fontFamily: fonts.sansSemiBold, fontSize: 11, color: colors.encre },
  textSmall: { fontFamily: fonts.sansMedium, fontSize: 10, color: colors.ardoise },
})
