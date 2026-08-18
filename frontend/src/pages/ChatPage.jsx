import { useEffect, useRef, useState } from 'react'
import { MessageSquare, Send, FileText, BookOpen } from 'lucide-react'
import { apiFetch, dossierFetch, getActiveDossierId } from '../config/api'
import { reflowText } from '../utils/text'

// 4 suggestions, pas 12 : un mur de boutons quasi identiques noyait l'écran
// vide plus qu'il ne l'aidait. Les 4 sujets fiscaux restent ceux testés
// dans les 3 langues (le reste du set FR/darija/arabe sert toujours de banc
// manuel pour la comparaison RAG, cf. test_langue.py) — ici on fait tourner
// la langue d'un sujet à l'autre pour montrer le bilinguisme sans répéter
// chaque question 3 fois. `rtl` sert uniquement à orienter le bouton — la
// darija latine (arabizi) reste en alphabet latin, seul l'arabe classique
// s'écrit de droite à gauche.
const SUGGESTIONS = [
  { text: 'Quelles sociétés sont exclues du champ de l\'IS ?' },
  { text: 'Chhal howa taux dyal TVA 3la les médicaments?' },
  { text: 'Quelles charges ne sont pas déductibles du résultat ?' },
  { text: 'كيفاش كيخدم نظام التسوية الذاتية ديال الضريبة على القيمة المضافة؟', rtl: true },
]

export default function ChatPage({ dossierId }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [activeLaw, setActiveLaw] = useState(null)
  const scrollRef = useRef(null)
  const textareaRef = useRef(null)

  // Reset la conversation au changement de dossier — sinon les anciennes
  // réponses (sourcées sur l'ancien dossier) restent affichées mélangées aux
  // nouvelles, sans que rien ne signale le changement de contexte.
  useEffect(() => {
    setMessages([])
    setActiveLaw(null)
  }, [dossierId])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const sendMessage = async (query) => {
    const text = (query || input).trim()
    if (!text || sending) return
    setInput('')
    setSending(true)
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: text },
      { role: 'assistant', content: null },
    ])
    try {
      const hasDossier = !!getActiveDossierId()
      const res = hasDossier
        ? await dossierFetch('/chat', {
            method: 'POST',
            body: JSON.stringify({ query: text, top_k: 5 }),
          })
        : await apiFetch('/chat/general', {
            method: 'POST',
            body: JSON.stringify({ query: text, top_k: 5 }),
      })
      if (!res.ok) throw new Error(`Erreur ${res.status}`)
      const data = await res.json()
      setMessages((prev) => {
        const next = [...prev]
        next[next.length - 1] = { role: 'assistant', content: data.answer, sources: data.sources }
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
      textareaRef.current?.focus()
    }
  }

  return (
    <div className="chat-shell">
      <div className="chat-main">
        {messages.length === 0 ? (
          <div className="conversation" ref={scrollRef}>
            <div className="empty-chat">
              <div className="empty-icon-wrap">
                <MessageSquare size={22} />
              </div>
              <div className="empty-title">Assistant fiscal</div>
              <div className="empty-sub">
                Posez une question fiscale. Nisab consulte le corpus du CGI et du Bulletin Officiel et répond en citant ses sources.
              </div>
              <div className="suggestions-grid">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s.text}
                    className="suggestion"
                    dir={s.rtl ? 'rtl' : undefined}
                    onClick={() => sendMessage(s.text)}
                  >
                    {s.text}
                    <span style={{ color: 'var(--seuil)', marginLeft: 6, opacity: 0.6 }}>→</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="conversation" ref={scrollRef}>
            {messages.map((m, i) => (
              <div key={i}>
                <div className={`msg-row ${m.role}`}>
                  {m.role === 'assistant' && <div className="msg-avatar">N</div>}
                  {/* Seule la bulle de reponse bascule en RTL, pas la page :
                      l'interface reste en francais (voir bloc 4 du plan), c'est
                      le contenu genere qui est arabe. */}
                  <div
                    className={`bubble${m.content == null ? ' loading' : ''}${m.langue === 'ar' || m.langue === 'ar_latin' ? ' msg-ar' : ''}`}
                    dir={m.langue === 'ar' || m.langue === 'ar_latin' ? 'rtl' : undefined}
                  >
                    {m.content ?? 'Consultation du corpus en cours…'}
                  </div>
                </div>
                {m.sources?.length > 0 && (
                  <div className="sources-strip">
                    {m.sources.map((s) => (
                      <button
                        key={s.id}
                        className={`source-pill${activeLaw?.id === s.id ? ' active' : ''}`}
                        onClick={() => setActiveLaw(activeLaw?.id === s.id ? null : s)}
                      >
                        <FileText size={10} />
                        {s.reference}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="composer-wrap">
          <div className="composer">
            <textarea
              ref={textareaRef}
              rows={1}
              placeholder="Ex. Quel est le régime de l'auto-liquidation de la TVA ?"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() } }}
              disabled={sending}
            />
            <button
              className="btn btn-primary btn-sm"
              onClick={() => sendMessage()}
              disabled={sending || !input.trim()}
            >
              {sending ? <span className="spinner" /> : <Send size={13} />}
            </button>
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--sourdine)', marginTop: 6, textAlign: 'center', lineHeight: 1.5 }}>
            Posez votre question en français, en arabe ou en darija — les références légales
            restent citées en français, telles qu'elles figurent au CGI.
          </div>
        </div>
      </div>

      <div className="law-panel">
        <div className="law-panel-header">
          <div className="law-panel-title">Articles de loi</div>
          <div className="law-panel-sub">Cliquez sur une source pour lire l'article complet</div>
        </div>
        <div className="law-panel-body">
          {activeLaw ? (
            <div className="law-article active">
              <div className="law-article-head">
                <div>
                  <div className="law-article-ref">{activeLaw.reference}</div>
                  <div className="law-article-source">{activeLaw.source_label}</div>
                </div>
                <div className="law-article-score">
                  <span className="mono">{activeLaw.score}</span>
                </div>
              </div>
              <div className="law-article-text">
                {reflowText(activeLaw.texte_complet || activeLaw.extrait)}
              </div>
            </div>
          ) : (
            <div className="law-empty">
              <BookOpen size={28} color="var(--bordure)" />
              <div className="law-empty-title">Aucun article sélectionné</div>
              <div className="law-empty-sub">Posez une question pour voir apparaître les articles de loi pertinents, puis cliquez sur une source pour lire le texte complet.</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
