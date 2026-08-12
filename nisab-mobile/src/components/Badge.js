import { StyleSheet, Text, View } from 'react-native'
import { radius } from '../theme'

/** Équivalent RN de frontend/src/components/ui/Badge.jsx — mêmes tons. */
export default function Badge({ tone, children }) {
  return (
    <View style={[styles.badge, { backgroundColor: tone.bg }]}>
      <Text style={[styles.text, { color: tone.fg }]}>{children}</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  badge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.full, alignSelf: 'flex-start' },
  text: { fontSize: 11.5, fontWeight: '600' },
})
