import { useEffect, useRef, useState } from 'react'
import {
  ActivityIndicator, KeyboardAvoidingView, Platform, ScrollView,
  StyleSheet, Text, TextInput, TouchableOpacity, View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { FileText, MessageSquare, Send, X } from 'lucide-react-native'
import { apiFetch } from '../config/api'
import { useDossier } from '../context/DossierContext'
import { colors, fonts, radius, spacing } from '../theme'

// Équivalent RN de frontend/src/pages/ChatPage.jsx — mêmes 4 suggestions
// (bancs manuels FR/darija/arabe, cf. test_langue.py), même contrat API
// (POST /dossiers/{id}/chat). Pas de panneau latéral "Articles de loi" :
// l'écran n'a pas la largeur pour deux colonnes, donc une source cliquée
// se déplie EN LIGNE sous la bulle plutôt que dans un panneau séparé — le
// texte complet est déjà dans la réponse (texte_complet par source), donc
// aucun appel réseau supplémentaire n'est nécessaire pour ce dépliant.
const SUGGESTIONS = [
  { text: 'Quelles sociétés sont exclues du champ de l\'IS ?' },
  { text: 'Chhal howa taux dyal TVA 3la les médicaments?' },
  { text: 'Quelles charges ne sont pas déductibles du résultat ?' },
  { text: 'كيفاش كيخدم نظام التسوية الذاتية ديال الضريبة على القيمة المضافة؟', rtl: true },
]

export default function AssistantScreen({ onClose }) {
  const { activeDossier } = useDossier()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [expanded, setExpanded] = useState(null) // `${msgIndex}:${sourceId}` ou null
  const scrollRef = useRef(null)

  // Reset à l'ouverture / au changement de dossier — sinon les réponses
  // sourcées sur un autre dossier resteraient affichées sans rien signaler
  // le changement de contexte (même règle que ChatPage.jsx web).
  useEffect(() => {
    setMessages([])
    setExpanded(null)
  }, [activeDossier?.id])

  const sendMessage = async (query) => {
    const text = (query || input).trim()
    if (!text || sending || !activeDossier) return
    setInput('')
    setSending(true)
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: text },
      { role: 'assistant', content: null },
    ])
    try {
      const res = await apiFetch(`/dossiers/${activeDossier.id}/chat`, {
        method: 'POST',
        body: JSON.stringify({ query: text, top_k: 5 }),
      })
      if (!res.ok) throw new Error(`Erreur ${res.status}`)
      const data = await res.json()
      setMessages((prev) => {
        const next = [...prev]
        next[next.length - 1] = { role: 'assistant', content: data.answer, sources: data.sources, langue: data.langue }
        return next
      })
    } catch (err) {
      setMessages((prev) => {
        const next = [...prev]
        next[next.length - 1] = { role: 'assistant', content: `Erreur : ${err.message}` }
        return next
      })
    } finally {
      setSending(false)
    }
  }

  const toggleSource = (msgIndex, sourceId) => {
    const key = `${msgIndex}:${sourceId}`
    setExpanded((prev) => (prev === key ? null : key))
  }

  return (
    <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Assistant fiscal</Text>
          {activeDossier && <Text style={styles.subtitle}>{activeDossier.raison_sociale}</Text>}
        </View>
        <TouchableOpacity onPress={onClose} style={styles.closeBtn} hitSlop={8}>
          <X size={20} color={colors.ardoise} />
        </TouchableOpacity>
      </View>

      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 12 : 0}
      >
        {!activeDossier ? (
          <View style={styles.empty}>
            <Text style={styles.emptySub}>Aucun dossier rattaché.</Text>
          </View>
        ) : messages.length === 0 ? (
          <View style={styles.empty}>
            <View style={styles.emptyIconWrap}>
              <MessageSquare size={22} color={colors.seuil} />
            </View>
            <Text style={styles.emptyTitle}>Posez une question fiscale</Text>
            <Text style={styles.emptySub}>
              Nisab consulte le corpus du CGI et du Bulletin Officiel et répond en citant ses sources.
            </Text>
            <View style={styles.suggestions}>
              {SUGGESTIONS.map((s) => (
                <TouchableOpacity key={s.text} style={styles.suggestion} onPress={() => sendMessage(s.text)}>
                  <Text style={[styles.suggestionText, s.rtl && { textAlign: 'right' }]}>{s.text}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        ) : (
          <ScrollView
            ref={scrollRef}
            contentContainerStyle={styles.conversation}
            onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: true })}
          >
            {messages.map((m, i) => {
              const rtl = m.langue === 'ar' || m.langue === 'ar_latin'
              return (
                <View key={i} style={{ marginBottom: spacing.md }}>
                  <View style={[styles.bubbleRow, m.role === 'user' && styles.bubbleRowUser]}>
                    <View style={[
                      styles.bubble,
                      m.role === 'user' ? styles.bubbleUser : styles.bubbleAssistant,
                    ]}>
                      {m.content == null ? (
                        <ActivityIndicator size="small" color={colors.seuil} />
                      ) : (
                        <Text style={[
                          m.role === 'user' ? styles.bubbleTextUser : styles.bubbleTextAssistant,
                          rtl && { textAlign: 'right' },
                        ]}>
                          {m.content}
                        </Text>
                      )}
                    </View>
                  </View>

                  {m.sources?.length > 0 && (
                    <View style={styles.sourcesRow}>
                      {m.sources.map((s) => {
                        const key = `${i}:${s.id}`
                        const active = expanded === key
                        return (
                          <TouchableOpacity
                            key={s.id}
                            style={[styles.sourcePill, active && styles.sourcePillActive]}
                            onPress={() => toggleSource(i, s.id)}
                          >
                            <FileText size={10} color={active ? colors.accentInk : colors.seuil} />
                            <Text style={[styles.sourcePillText, active && styles.sourcePillTextActive]}>
                              {s.reference}
                            </Text>
                          </TouchableOpacity>
                        )
                      })}
                    </View>
                  )}

                  {m.sources?.map((s) => {
                    const key = `${i}:${s.id}`
                    if (expanded !== key) return null
                    return (
                      <View key={`${key}-text`} style={styles.lawText}>
                        <Text style={styles.lawTextSource}>{s.source_label}</Text>
                        <Text style={styles.lawTextBody}>{s.texte_complet || s.extrait}</Text>
                      </View>
                    )
                  })}
                </View>
              )
            })}
          </ScrollView>
        )}

        <View style={styles.composerWrap}>
          <View style={styles.composer}>
            <TextInput
              style={styles.input}
              placeholder="Ex. Quel est le régime de l'auto-liquidation de la TVA ?"
              placeholderTextColor={colors.sourdine}
              value={input}
              onChangeText={setInput}
              multiline
              editable={!!activeDossier && !sending}
            />
            <TouchableOpacity
              style={[styles.sendBtn, (!input.trim() || sending || !activeDossier) && styles.sendBtnDisabled]}
              onPress={() => sendMessage()}
              disabled={!input.trim() || sending || !activeDossier}
            >
              {sending ? <ActivityIndicator size="small" color={colors.accentInk} /> : <Send size={14} color={colors.accentInk} />}
            </TouchableOpacity>
          </View>
          <Text style={styles.disclaimer}>
            Les références légales restent citées en français, telles qu'elles figurent au CGI.
          </Text>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.toile },
  header: {
    flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm,
    paddingHorizontal: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing.sm,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.bordure,
  },
  title: { fontFamily: fonts.display, fontSize: 18, color: colors.encre },
  subtitle: { fontFamily: fonts.sans, fontSize: 12, color: colors.sourdine, marginTop: 2 },
  closeBtn: { padding: spacing.xs },

  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: spacing.xl },
  emptyIconWrap: {
    width: 44, height: 44, borderRadius: radius.full, backgroundColor: colors.seuilSoft,
    alignItems: 'center', justifyContent: 'center', marginBottom: spacing.md,
  },
  emptyTitle: { fontFamily: fonts.sansSemiBold, fontSize: 14.5, color: colors.encre, marginBottom: 4 },
  emptySub: { fontFamily: fonts.sans, fontSize: 12.5, color: colors.sourdine, textAlign: 'center', lineHeight: 18 },
  suggestions: { marginTop: spacing.lg, width: '100%', gap: spacing.sm },
  suggestion: {
    borderWidth: 1, borderColor: colors.bordure, borderRadius: radius.card,
    backgroundColor: colors.surface, paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
  },
  suggestionText: { fontFamily: fonts.sans, fontSize: 12.5, color: colors.ardoise, lineHeight: 18 },

  conversation: { padding: spacing.lg, paddingBottom: spacing.xl },
  bubbleRow: { flexDirection: 'row' },
  bubbleRowUser: { justifyContent: 'flex-end' },
  bubble: { maxWidth: '86%', borderRadius: radius.card, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  bubbleUser: { backgroundColor: colors.seuil },
  bubbleAssistant: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.bordure },
  bubbleTextUser: { fontFamily: fonts.sans, fontSize: 13, color: colors.accentInk, lineHeight: 19 },
  bubbleTextAssistant: { fontFamily: fonts.sans, fontSize: 13, color: colors.encre, lineHeight: 19 },

  sourcesRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, marginTop: spacing.xs },
  sourcePill: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    borderWidth: 1, borderColor: colors.seuil, borderRadius: radius.sm,
    paddingHorizontal: spacing.sm, paddingVertical: 4,
  },
  sourcePillActive: { backgroundColor: colors.seuil },
  sourcePillText: { fontFamily: fonts.monoSemiBold, fontSize: 10.5, color: colors.seuil },
  sourcePillTextActive: { color: colors.accentInk },

  lawText: {
    marginTop: spacing.xs, borderWidth: 1, borderColor: colors.bordure, borderRadius: radius.card,
    backgroundColor: colors.surface, padding: spacing.md,
  },
  lawTextSource: { fontFamily: fonts.monoMedium, fontSize: 10, color: colors.sourdine, marginBottom: 4 },
  lawTextBody: { fontFamily: fonts.sans, fontSize: 12, color: colors.ardoise, lineHeight: 18 },

  composerWrap: {
    paddingHorizontal: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing.md,
    backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.bordure,
  },
  composer: { flexDirection: 'row', alignItems: 'flex-end', gap: spacing.sm },
  input: {
    flex: 1, maxHeight: 100, borderWidth: 1, borderColor: colors.bordure, borderRadius: radius.card,
    backgroundColor: colors.toile, paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    fontFamily: fonts.sans, fontSize: 13, color: colors.encre,
  },
  sendBtn: {
    width: 38, height: 38, borderRadius: radius.full, backgroundColor: colors.seuil,
    alignItems: 'center', justifyContent: 'center',
  },
  sendBtnDisabled: { backgroundColor: colors.surface2 },
  disclaimer: { fontFamily: fonts.sans, fontSize: 10.5, color: colors.sourdine, textAlign: 'center', marginTop: spacing.sm, lineHeight: 15 },
})
