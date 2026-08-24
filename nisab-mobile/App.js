import { StatusBar } from 'expo-status-bar'
import { useCallback, useState } from 'react'
import { ActivityIndicator, Modal, Platform, StyleSheet, Text, TouchableOpacity, View } from 'react-native'
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context'
import { AlertTriangle, CalendarClock, LogOut, MessageSquare, TrafficCone } from 'lucide-react-native'
import * as SplashScreen from 'expo-splash-screen'
import { useFonts as useIBMPlexSans, IBMPlexSans_400Regular, IBMPlexSans_500Medium, IBMPlexSans_600SemiBold, IBMPlexSans_700Bold } from '@expo-google-fonts/ibm-plex-sans'
import { useFonts as useIBMPlexMono, IBMPlexMono_400Regular, IBMPlexMono_500Medium, IBMPlexMono_600SemiBold } from '@expo-google-fonts/ibm-plex-mono'
import { useFonts as useSourceSerif4, SourceSerif4_600SemiBold, SourceSerif4_700Bold } from '@expo-google-fonts/source-serif-4'
import { AuthProvider, useAuth } from './src/context/AuthContext'
import { DossierProvider } from './src/context/DossierContext'
import LoginScreen from './src/screens/LoginScreen'
import FeuxScreen from './src/screens/FeuxScreen'
import EcheancesScreen from './src/screens/EcheancesScreen'
import AlertesScreen from './src/screens/AlertesScreen'
import AssistantScreen from './src/screens/AssistantScreen'
import { colors, fonts, radius, spacing } from './src/theme'

// SafeAreaView de 'react-native' est déprécié ET, sur Android, ne calcule
// jamais correctement les marges de la barre de statut/de gestes (le topbar
// venait chevaucher l'horloge du téléphone) — react-native-safe-area-context
// est la lib qui calcule les vraies zones sûres, nécessite un
// <SafeAreaProvider> à la racine de l'arbre (cf. export App() plus bas).

// Garde le splash natif affiché tant que les 3 familles de polices Direction
// D (IBM Plex Sans/Mono + Source Serif 4, cf. theme.js::fonts) ne sont pas
// chargées — sinon un premier rendu flashe en police système avant de
// re-render en police custom (FOUT), visible sur un cold start.
SplashScreen.preventAutoHideAsync()

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
  const [assistantOpen, setAssistantOpen] = useState(false)
  const ActiveScreen = TABS.find((t) => t.key === tab).Screen

  return (
    <DossierProvider>
      <SafeAreaView style={styles.screen}>
        <View style={styles.topbar}>
          {/* Direction D retire le carré de logo (frontend/src/components/
              layout/Sidebar.jsx:10, .brand-mark { display:none } dans
              App.css) — la marque, c'est le mot "Nisab" en Source Serif 4,
              plus aucun pictogramme. */}
          <Text style={styles.brand}>Nisab</Text>
          <Text style={styles.topbarUser} numberOfLines={1}>{user?.nom_complet || user?.email}</Text>
          <TouchableOpacity onPress={logout} style={styles.logoutBtn}>
            <LogOut size={16} color={colors.ardoise} />
          </TouchableOpacity>
        </View>

        <View style={styles.body}>
          <ActiveScreen />

          {/* Persistant sur les 3 onglets (rendu ici, pas dans ActiveScreen)
              plutôt qu'un 4e onglet : l'assistant n'est pas une section au
              même niveau que Situation/Échéances/Alertes, c'est une action
              transverse toujours disponible — cf. demande explicite de ne
              pas le mettre dans TABS. */}
          <TouchableOpacity
            style={styles.assistantFab}
            onPress={() => setAssistantOpen(true)}
            activeOpacity={0.85}
          >
            <MessageSquare size={22} color={colors.accentInk} />
          </TouchableOpacity>
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

      <Modal
        visible={assistantOpen}
        animationType="slide"
        onRequestClose={() => setAssistantOpen(false)}
      >
        <AssistantScreen onClose={() => setAssistantOpen(false)} />
      </Modal>
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
  const [sansLoaded] = useIBMPlexSans({ IBMPlexSans_400Regular, IBMPlexSans_500Medium, IBMPlexSans_600SemiBold, IBMPlexSans_700Bold })
  const [monoLoaded] = useIBMPlexMono({ IBMPlexMono_400Regular, IBMPlexMono_500Medium, IBMPlexMono_600SemiBold })
  const [displayLoaded] = useSourceSerif4({ SourceSerif4_600SemiBold, SourceSerif4_700Bold })
  const fontsReady = sansLoaded && monoLoaded && displayLoaded

  const onLayoutRootView = useCallback(async () => {
    if (fontsReady) await SplashScreen.hideAsync()
  }, [fontsReady])

  if (!fontsReady) return null

  return (
    <SafeAreaProvider onLayout={onLayoutRootView}>
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
  brand: { fontFamily: fonts.display, fontSize: 17, color: colors.encre, letterSpacing: -0.2 },
  topbarUser: { flex: 1, fontFamily: fonts.sans, fontSize: 12.5, color: colors.ardoise, textAlign: 'right' },
  logoutBtn: { padding: spacing.xs },
  body: { flex: 1 },
  // Position ancrée au coin bas-droit du conteneur `body` (pas de la
  // SafeAreaView entière) : elle reste au-dessus du contenu scrollable mais
  // toujours au-dessus de la tabbar, quel que soit l'onglet actif.
  assistantFab: {
    position: 'absolute', right: spacing.lg, bottom: spacing.lg,
    width: 52, height: 52, borderRadius: radius.full, backgroundColor: colors.seuil,
    alignItems: 'center', justifyContent: 'center',
    ...Platform.select({
      ios: { shadowColor: '#1e0f0a', shadowOpacity: 0.22, shadowRadius: 10, shadowOffset: { width: 0, height: 6 } },
      android: { elevation: 5 },
    }),
  },
  tabbar: {
    flexDirection: 'row', backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.bordure,
    paddingVertical: spacing.sm,
  },
  tabItem: { flex: 1, alignItems: 'center', gap: 2 },
  tabLabel: { fontFamily: fonts.sansMedium, fontSize: 10.5, color: colors.sourdine },
  tabLabelActive: { fontFamily: fonts.sansSemiBold, color: colors.seuil },
})
