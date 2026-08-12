import { StatusBar } from 'expo-status-bar'
import { useState } from 'react'
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, View } from 'react-native'
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context'
import { AlertTriangle, CalendarClock, LogOut, TrafficCone } from 'lucide-react-native'
import { AuthProvider, useAuth } from './src/context/AuthContext'
import { DossierProvider } from './src/context/DossierContext'
import LoginScreen from './src/screens/LoginScreen'
import FeuxScreen from './src/screens/FeuxScreen'
import EcheancesScreen from './src/screens/EcheancesScreen'
import AlertesScreen from './src/screens/AlertesScreen'
import { colors, spacing } from './src/theme'

// SafeAreaView de 'react-native' est déprécié ET, sur Android, ne calcule
// jamais correctement les marges de la barre de statut/de gestes (le topbar
// venait chevaucher l'horloge du téléphone) — react-native-safe-area-context
// est la lib qui calcule les vraies zones sûres, nécessite un
// <SafeAreaProvider> à la racine de l'arbre (cf. export App() plus bas).

// Routing manuel par useState, comme frontend/src/App.jsx:75 (pas de
// react-router côté web) — même convention côté mobile, pas de
// @react-navigation pour 3 écrans plats sans hiérarchie de navigation.
const TABS = [
  { key: 'feux', label: 'Situation', Icon: TrafficCone, Screen: FeuxScreen },
  { key: 'echeances', label: 'Échéances', Icon: CalendarClock, Screen: EcheancesScreen },
  { key: 'alertes', label: 'Alertes', Icon: AlertTriangle, Screen: AlertesScreen },
]

function AuthenticatedApp() {
  const { user, logout } = useAuth()
  const [tab, setTab] = useState('feux')
  const ActiveScreen = TABS.find((t) => t.key === tab).Screen

  return (
    <DossierProvider>
      <SafeAreaView style={styles.screen}>
        <View style={styles.topbar}>
          <View style={styles.logo}>
            <Text style={styles.logoText}>N</Text>
          </View>
          <Text style={styles.topbarUser} numberOfLines={1}>{user?.nom_complet || user?.email}</Text>
          <TouchableOpacity onPress={logout} style={styles.logoutBtn}>
            <LogOut size={16} color={colors.ardoise} />
          </TouchableOpacity>
        </View>

        <View style={styles.body}>
          <ActiveScreen />
        </View>

        <View style={styles.tabbar}>
          {TABS.map(({ key, label, Icon }) => {
            const active = key === tab
            return (
              <TouchableOpacity key={key} style={styles.tabItem} onPress={() => setTab(key)}>
                <Icon size={20} color={active ? colors.seuil : colors.sourdine} />
                <Text style={[styles.tabLabel, active && styles.tabLabelActive]}>{label}</Text>
              </TouchableOpacity>
            )
          })}
        </View>
        <StatusBar style="auto" />
      </SafeAreaView>
    </DossierProvider>
  )
}

function Root() {
  const { status } = useAuth()

  if (status === 'loading') {
    return (
      <SafeAreaView style={[styles.screen, styles.center]}>
        <ActivityIndicator color={colors.seuil} size="large" />
      </SafeAreaView>
    )
  }

  return status === 'authenticated' ? <AuthenticatedApp /> : <LoginScreen />
}

export default function App() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <Root />
      </AuthProvider>
    </SafeAreaProvider>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.toile },
  center: { justifyContent: 'center', alignItems: 'center' },
  topbar: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.sm,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.bordure,
  },
  logo: { width: 28, height: 28, borderRadius: 7, backgroundColor: colors.seuil, alignItems: 'center', justifyContent: 'center' },
  logoText: { color: '#fff', fontWeight: '700', fontSize: 13 },
  topbarUser: { flex: 1, fontSize: 12.5, color: colors.ardoise },
  logoutBtn: { padding: spacing.xs },
  body: { flex: 1 },
  tabbar: {
    flexDirection: 'row', backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.bordure,
    paddingVertical: spacing.sm,
  },
  tabItem: { flex: 1, alignItems: 'center', gap: 2 },
  tabLabel: { fontSize: 10.5, color: colors.sourdine },
  tabLabelActive: { color: colors.seuil, fontWeight: '600' },
})
