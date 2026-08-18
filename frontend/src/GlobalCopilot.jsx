import { useEffect, useRef, useState } from "react"
import { MessageSquare, X, Send, Check, ChevronDown, Minimize2, Sparkles } from "lucide-react"
import { dossierFetch } from "./config/api"
import { reflowText } from "./utils/text"

const VIEW_SUGGESTIONS = {
  dashboard: [
    "Résume-moi la situation fiscale actuelle",
    "Quelles sont les urgences de la semaine ?",
    "Comment améliorer mon score de conformité ?",
  ],
  audit: [
    "Explique-moi la première anomalie détectée",
    "Quel est le risque de redressement ?",
    "Comment régulariser les anomalies critiques ?",
  ],
  calendar: [
    "Quelles sont mes prochaines échéances TVA ?",
    "Quelles pénalités en cas de retard de déclaration ?",
  ],
  odoo: [
    "Comment connecter Odoo à Nisab ?",
    "Que signifie le mode démonstration ?",
  ],
  admin: [
    "Comment valider les articles du corpus ?",
    "Que fait le pipeline d'\''ingestion ?",
  ],
}

const VIEW_NAMES = {
  dashboard: "Tableau de bord",
  audit: "Audit fiscal",
  calendar: "Calendrier fiscal",
  odoo: "Synchronisation ERP",
  admin: "Administration",
  chat: "Assistant fiscal",
}

export default function GlobalCopilot({ activeView, findings, dossierId }) {
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState("")
  const [sending, setSending] = useState(false)
  const [activeLaw, setActiveLaw] = useState(null)
  const [minimized, setMinimized] = useState(false)
  const scrollRef = useRef(null)
  const textareaRef = useRef(null)

  // Le composant reste monté d'une vue à l'autre (voir COPILOT_VIEWS dans
  // App.jsx) — sans ça, changer de dossier laisserait l'historique de
  // conversation de l'ancien dossier affiché à côté des réponses du nouveau.
  useEffect(() => {
    setMessages([])
    setActiveLaw(null)
  }, [dossierId])

  const buildContextPayload = () => {
    if (!findings || findings.length === 0) return null
    return {
      view: activeView,
      anomalies_count: findings.length,
      anomalies: findings.slice(0, 3).map(f => ({
        title: f.title,
        severity: f.severity,
        invoice: f.invoice,
        amount_risk: f.categorie_montant === 'non_calculable' ? null : f.amount_risk,
        recommendation: f.recommendation,
      })),
    }
  }

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [messages])

  useEffect(() => {
    if (isOpen) setTimeout(() => textareaRef.current?.focus(), 300)
  }, [isOpen])

  const sendMessage = async (query) => {
    const text = (query || input).trim()
    if (!text || sending) return
    setInput("")
    setSending(true)
    setMessages(prev => [
      ...prev,
      { role: "user", content: text },
      { role: "assistant", content: null },
    ])
    try {
      const res = await dossierFetch("/chat", {
        method: "POST",
        body: JSON.stringify({ query: text, top_k: 5, context_data: buildContextPayload(), active_view: activeView }),
      })
      if (!res.ok) throw new Error(`Erreur ${res.status}`)
      const data = await res.json()
      setMessages(prev => {
        const next = [...prev]
        next[next.length - 1] = { role: "assistant", content: data.answer, sources: data.sources }
        return next
      })
    } catch (err) {
      setMessages(prev => {
        const next = [...prev]
        next[next.length - 1] = { role: "assistant", content: `Erreur : ${err.message}` }
        return next
      })
    } finally {
      setSending(false)
      textareaRef.current?.focus()
    }
  }

  const suggestions = VIEW_SUGGESTIONS[activeView] || VIEW_SUGGESTIONS.dashboard

  return (
    <>
      {/* FAB — carré plein, icône seule (cf. .fab du CSS source de
          l'artifact) ; le titre a été retiré du bouton lui-même, il reste
          disponible via l'infobulle. */}
      <button
        className={`copilot-fab${isOpen ? " copilot-fab--active" : ""}`}
        onClick={() => { setIsOpen(o => !o); setMinimized(false) }}
        id="copilot-fab-btn"
        title="Copilote Nisab IA"
      >
        {isOpen ? <X size={20} /> : <MessageSquare size={20} />}
      </button>

      {/* Plus d'overlay plein écran : le tiroir est une carte flottante
          compacte ancrée près du FAB, pas un panneau qui capture toute
          l'attention — pas besoin d'assombrir le reste de la page. */}

      {/* Drawer */}
      <div className={`copilot-drawer${isOpen ? " copilot-drawer--open" : ""}${minimized ? " copilot-drawer--minimized" : ""}`}>

        {/* Header */}
        <div className="copilot-header">
          <div className="copilot-header-left">
            <div className="copilot-avatar"><Sparkles size={13} /></div>
            <div>
              <div className="copilot-header-title">Nisab IA</div>
              <div className="copilot-header-sub">{VIEW_NAMES[activeView] || "Copilote"} · contexte actif</div>
            </div>
          </div>
          <div className="copilot-header-actions">
            <button className="copilot-icon-btn" onClick={() => setMinimized(m => !m)} title="Réduire">
              {minimized ? <ChevronDown size={15} /> : <Minimize2 size={15} />}
            </button>
            <button className="copilot-icon-btn" onClick={() => setIsOpen(false)} title="Fermer">
              <X size={15} />
            </button>
          </div>
        </div>

        {/* Context badge */}
        {!minimized && findings && findings.length > 0 && (
          <div className="copilot-context-badge">
            <span className="copilot-context-dot" />
            {findings.length} anomalie(s) chargées en contexte
          </div>
        )}

        {!minimized && (
          <div className="copilot-body">
            <div className="copilot-conversation" ref={scrollRef}>
              {messages.length === 0 ? (
                <div className="copilot-empty">
                  <div className="copilot-empty-icon"><Sparkles size={18} /></div>
                  <div className="copilot-empty-title">Comment puis-je vous aider ?</div>
                  <div className="copilot-empty-sub">
                    Je connais votre contexte actuel. Posez une question fiscale ou sur les données affichées.
                  </div>
                  <div className="copilot-suggestions">
                    {suggestions.map((s, i) => (
                      <button key={i} className="copilot-suggestion" onClick={() => sendMessage(s)}>{s}</button>
                    ))}
                  </div>
                </div>
              ) : (
                messages.map((m, i) => (
                  <div key={i}>
                    {/* Plus d'avatar par bulle : déjà porté une fois par
                        l'en-tête du tiroir, en remettre un par message était
                        redondant. */}
                    <div className={`copilot-msg-row ${m.role}`}>
                      <div className={`copilot-bubble${m.content == null ? " copilot-bubble--loading" : ""}`}>
                        {m.content ?? "Analyse en cours…"}
                      </div>
                    </div>
                    {m.sources?.length > 0 && (
                      <div className="copilot-sources">
                        {m.sources.map(s => (
                          <button
                            key={s.id}
                            className={`copilot-source-pill${activeLaw?.id === s.id ? " active" : ""}`}
                            onClick={() => setActiveLaw(activeLaw?.id === s.id ? null : s)}
                          >
                            <Check size={10} />
                            {s.reference}
                          </button>
                        ))}
                      </div>
                    )}
                    {activeLaw && m.sources?.some(s => s.id === activeLaw.id) && (
                      <div className="copilot-law-preview">
                        <div className="copilot-law-ref">{activeLaw.reference}</div>
                        <div className="copilot-law-text">{reflowText(activeLaw.texte_complet || activeLaw.extrait)}</div>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>

            <div className="copilot-composer-wrap">
              <div className="copilot-composer">
                <textarea
                  ref={textareaRef}
                  rows={1}
                  placeholder="Posez une question fiscale…"
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage() } }}
                  disabled={sending}
                />
                <button
                  className="copilot-send-btn"
                  onClick={() => sendMessage()}
                  disabled={sending || !input.trim()}
                >
                  {sending ? <span className="spinner" style={{ width: 13, height: 13, borderWidth: 1.5 }} /> : <Send size={13} />}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
