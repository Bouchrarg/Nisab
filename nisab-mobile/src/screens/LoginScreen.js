import { useState } from 'react'
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { useAuth } from '../context/AuthContext'
import { colors, fonts, radius, spacing } from '../theme'

export default function LoginScreen() {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async () => {
    if (!email.trim() || !password) return
    setError('')
    setSubmitting(true)
    try {
      await login(email.trim(), password)
    } catch (e) {
      setError(e.message || 'Échec de connexion')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <SafeAreaView style={styles.screen}>
      <KeyboardAvoidingView
        style={styles.center}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        {/* Direction D : plus de pictogramme de marque, seulement le mot
            "Nisab" en Source Serif 4 — même choix que Sidebar.jsx côté web
            (.brand-mark { display:none }), cf. App.js. */}
        <Text style={styles.title}>Nisab</Text>
        <Text style={styles.subtitle}>Espace dirigeant</Text>

        <View style={styles.form}>
          <TextInput
            style={styles.input}
            placeholder="Email"
            placeholderTextColor={colors.sourdine}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="email-address"
            value={email}
            onChangeText={setEmail}
          />
          <TextInput
            style={styles.input}
            placeholder="Mot de passe"
            placeholderTextColor={colors.sourdine}
            secureTextEntry
            value={password}
            onChangeText={setPassword}
          />

          {error ? <Text style={styles.error}>{error}</Text> : null}

          <TouchableOpacity
            style={[styles.button, submitting && styles.buttonDisabled]}
            onPress={handleSubmit}
            disabled={submitting}
          >
            {submitting ? (
              <ActivityIndicator color={colors.accentInk} />
            ) : (
              <Text style={styles.buttonText}>Se connecter</Text>
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.toile },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', paddingHorizontal: spacing.xl },
  title: { fontFamily: fonts.displayBold, fontSize: 32, color: colors.encre, letterSpacing: -0.4 },
  subtitle: { fontFamily: fonts.sans, fontSize: 13, color: colors.sourdine, marginTop: 4, marginBottom: spacing.xxl },
  form: { width: '100%', gap: spacing.md },
  input: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.bordure,
    borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.md,
    fontFamily: fonts.sans, fontSize: 14, color: colors.encre,
  },
  error: { fontFamily: fonts.sans, color: colors.critique, fontSize: 12.5 },
  button: {
    backgroundColor: colors.seuil, borderRadius: radius.md, paddingVertical: spacing.md,
    alignItems: 'center', marginTop: spacing.xs,
  },
  buttonDisabled: { opacity: 0.6 },
  buttonText: { fontFamily: fonts.sansSemiBold, color: colors.accentInk, fontSize: 14 },
})
