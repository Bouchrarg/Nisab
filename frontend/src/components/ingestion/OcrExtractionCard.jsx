import { useRef, useState } from 'react'
import { Upload, ScanText, AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react'
import { apiFetch } from '../../config/api'

const EXTENSIONS = '.jpg,.jpeg,.png'

//: Libellés lisibles pour les 4 champs que backend/app/ocr_extraction.py
//: essaie d'extraire. L'ordre ici est l'ordre d'affichage.
const CHAMPS = [
  { key: 'numero_piece', label: 'N° de pièce' },
  { key: 'date', label: 'Date' },
  { key: 'montant_ttc', label: 'Montant TTC' },
  { key: 'ice', label: 'ICE' },
]

/**
 * Extraction OCR de facture (palier "petit peu" du plan, pas une Phase 5 bis).
 *
 * Différence structurante avec ImportFichierCard : ceci ne persiste rien.
 * `POST /dossiers/{id}/ocr/extraire` ne touche jamais aux données du
 * dossier ni à ai_auditor — voir ocr_extraction.py côté backend pour
 * pourquoi (une image ne donne jamais les comptes du plan CGNC, on ne
 * fabrique pas une écriture à partir d'une hypothèse). Donc pas de bandeau
 * "conforme" en cas de succès ici, contrairement à l'import CSV : le
 * résultat reste "à vérifier" même quand l'extraction a marché.
 */
export default function OcrExtractionCard({ dossierId }) {
  const inputRef = useRef(null)
  const [drag, setDrag] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [texteOuvert, setTexteOuvert] = useState(false)

  const envoyer = async (fichier) => {
    if (!fichier) return
    if (!dossierId) {
      setError("Sélectionnez d'abord un dossier.")
      return
    }
    setLoading(true)
    setError(null)
    setResult(null)
    setTexteOuvert(false)
    try {
      const form = new FormData()
      form.append('file', fichier)
      const res = await apiFetch(`/dossiers/${dossierId}/ocr/extraire`, { method: 'POST', body: form })
      if (!res.ok) {
        const body = await res.json().catch(() => null)
        throw new Error(body?.detail || `L'extraction a échoué (code ${res.status}).`)
      }
      setResult(await res.json())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <div className="card" style={{ marginTop: 20 }}>
      <div className="card-header">
        <span className="card-title">Extraction OCR (facture scannée)</span>
        <span className="badge neutral">Expérimental</span>
      </div>
      <div className="card-body">
        <p style={{ fontSize: 13, color: 'var(--ardoise)', lineHeight: 1.6, marginBottom: 14 }}>
          Dépose la photo ou le scan d'une facture : Nisab en tire quelques champs
          (date, montant TTC, ICE, n° de pièce) pour t'éviter de les retaper. Rien
          n'est enregistré et aucune écriture comptable n'est créée — une image ne
          dit jamais quel compte du plan comptable mouvementer, seulement toi.
        </p>

        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); envoyer(e.dataTransfer.files?.[0]) }}
          onClick={() => inputRef.current?.click()}
          style={{
            border: `1.5px dashed ${drag ? 'var(--seuil)' : 'var(--bordure)'}`,
            background: drag ? 'var(--seuil-soft)' : 'var(--toile)',
            borderRadius: 'var(--radius-card)',
            padding: '26px 18px',
            textAlign: 'center',
            cursor: loading ? 'default' : 'pointer',
            transition: 'border-color .15s, background .15s',
            marginBottom: 14,
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept={EXTENSIONS}
            style={{ display: 'none' }}
            onChange={(e) => envoyer(e.target.files?.[0])}
          />
          {loading ? (
            <><span className="spinner dark" /> <span style={{ fontSize: 13, color: 'var(--ardoise)' }}>Lecture de l'image…</span></>
          ) : (
            <>
              <ScanText size={22} style={{ color: 'var(--sourdine)' }} />
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--encre)', marginTop: 8 }}>
                Déposez une photo de facture ici, ou cliquez pour la choisir
              </div>
              <div style={{ fontSize: 12, color: 'var(--sourdine)', marginTop: 4 }}>
                Formats acceptés : JPG, PNG — 5 Mo maximum
              </div>
            </>
          )}
        </div>

        <button className="btn btn-primary btn-sm" onClick={() => inputRef.current?.click()} disabled={loading}>
          <Upload size={13} /> Choisir une image
        </button>

        {error && (
          <div className="alert critique" style={{ marginTop: 14 }}>
            <div className="alert-dot" />
            <div><strong>Extraction impossible</strong> — {error}</div>
          </div>
        )}

        {result && (
          <div style={{ marginTop: 14 }}>
            {/* Vigilance, pas conforme : même un succès reste une hypothèse
                non vérifiée, voir la docstring d'ocr_extraction.py. */}
            <div className="alert vigilance">
              <div className="alert-dot" />
              <div>{result.avertissement}</div>
            </div>

            <div style={{
              display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10,
              marginTop: 10, fontSize: 13,
            }}>
              {CHAMPS.map(({ key, label }) => (
                <div key={key} style={{
                  border: '1px solid var(--bordure)', borderRadius: 'var(--radius-card)',
                  padding: '8px 10px', background: 'var(--toile)',
                }}>
                  <div style={{ fontSize: 11, color: 'var(--sourdine)', marginBottom: 2 }}>{label}</div>
                  <div className="mono" style={{ fontWeight: 600, color: result.champs[key] ? 'var(--encre)' : 'var(--sourdine)' }}>
                    {result.champs[key] ?? 'non détecté'}
                  </div>
                </div>
              ))}
            </div>

            <div style={{ fontSize: 12, color: 'var(--sourdine)', marginTop: 10 }}>
              Confiance de lecture moyenne : <span className="mono">{Math.round(result.confiance_moyenne * 100)}%</span>
            </div>

            <button
              type="button"
              className="btn btn-ghost btn-sm"
              style={{ marginTop: 10 }}
              onClick={() => setTexteOuvert((v) => !v)}
            >
              {texteOuvert ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              {texteOuvert ? 'Masquer' : 'Voir'} le texte brut reconnu ({result.texte_brut.length} ligne{result.texte_brut.length > 1 ? 's' : ''})
            </button>

            {texteOuvert && (
              <ul style={{ margin: '8px 0 0 16px', fontSize: 12, lineHeight: 1.7, color: 'var(--ardoise)' }}>
                {result.texte_brut.map((l, i) => (
                  <li key={i}>
                    {l.texte} <span className="mono" style={{ color: 'var(--sourdine)' }}>({Math.round(l.confiance * 100)}%)</span>
                  </li>
                ))}
              </ul>
            )}

            {result.confiance_moyenne < 0.85 && (
              <div className="alert critique" style={{ marginTop: 10 }}>
                <div className="alert-dot" />
                <div>
                  <AlertTriangle size={13} style={{ verticalAlign: -2 }} /> Confiance de lecture faible — vérifie
                  chaque champ avant de t'en servir, l'image est probablement floue ou mal cadrée.
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
