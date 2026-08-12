import { useRef, useState } from 'react'
import { Upload, Download, FileSpreadsheet, CheckCircle2, AlertTriangle } from 'lucide-react'
import { apiFetch } from '../../config/api'

const EXTENSIONS = '.csv,.txt,.xlsx,.xls'

/**
 * Import d'un export comptable CSV/Excel (Phase 5, Module 1).
 *
 * C'est la carte qui matérialise « Nisab ne dépend plus d'Odoo » : le fichier
 * importé alimente exactement le même pipeline d'audit, sans qu'aucune ligne du
 * moteur n'ait changé.
 *
 * L'import FUSIONNE plutôt qu'il ne remplace (voir
 * _fusionner_donnees_comptables côté backend) : les pièces déjà présentes et
 * absentes de ce fichier restent intactes, seules celles au même n° de pièce
 * sont mises à jour. D'où la confirmation avant envoi — l'action reste une
 * écriture sur le dossier, même si elle n'écrase plus tout.
 *
 * L'upload passe par apiFetch avec un FormData — le wrapper ne force pas
 * Content-Type dans ce cas, c'est le navigateur qui pose la boundary multipart.
 */
export default function ImportFichierCard({ dossierId, dossierNom, onImported }) {
  const inputRef = useRef(null)
  const [drag, setDrag] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  const envoyer = async (fichier) => {
    if (!fichier) return
    if (!dossierId) {
      setError("Sélectionnez d'abord un dossier avant d'importer.")
      return
    }
    const confirme = window.confirm(
      `Ce fichier va être fusionné aux données comptables déjà présentes dans « ${dossierNom || 'ce dossier'} » : `
      + 'les pièces portant un n° déjà connu seront mises à jour, les autres seront ajoutées. Continuer ?'
    )
    if (!confirme) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const form = new FormData()
      form.append('file', fichier)
      const res = await apiFetch(`/dossiers/${dossierId}/import/fichier`, { method: 'POST', body: form })
      if (!res.ok) {
        const body = await res.json().catch(() => null)
        throw new Error(body?.detail || `L'import a échoué (code ${res.status}).`)
      }
      const data = await res.json()
      setResult(data)
      onImported?.(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const telechargerModele = async () => {
    if (!dossierId) {
      setError("Sélectionnez d'abord un dossier.")
      return
    }
    try {
      const res = await apiFetch(`/dossiers/${dossierId}/import/modele`)
      if (!res.ok) throw new Error('Modèle indisponible.')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'modele_import_nisab.csv'
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div className="card" style={{ marginTop: 20 }}>
      <div className="card-header">
        <span className="card-title">Import de fichier comptable</span>
        <span className="badge conforme">CSV · Excel</span>
      </div>
      <div className="card-body">
        <p style={{ fontSize: 13, color: 'var(--ardoise)', lineHeight: 1.6, marginBottom: 14 }}>
          Pour un cabinet sans Odoo, ou pour un dossier tenu sous Sage&nbsp;: exportez le
          grand livre en CSV ou Excel. Les écritures alimentent le même moteur d'audit et le
          même calendrier fiscal que la synchronisation ERP. Un import s'ajoute aux données déjà
          présentes (les pièces déjà connues sont mises à jour, les autres conservées).
          {dossierNom && <> Destination&nbsp;: <strong>{dossierNom}</strong>.</>}
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
            <><span className="spinner dark" /> <span style={{ fontSize: 13, color: 'var(--ardoise)' }}>Analyse du fichier…</span></>
          ) : (
            <>
              <FileSpreadsheet size={22} style={{ color: 'var(--sourdine)' }} />
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--encre)', marginTop: 8 }}>
                Déposez votre fichier ici, ou cliquez pour le choisir
              </div>
              <div style={{ fontSize: 12, color: 'var(--sourdine)', marginTop: 4 }}>
                Formats acceptés : CSV, Excel — 10 Mo maximum
              </div>
            </>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-primary btn-sm" onClick={() => inputRef.current?.click()} disabled={loading}>
            <Upload size={13} /> Choisir un fichier
          </button>
          <button className="btn btn-ghost btn-sm" onClick={telechargerModele} disabled={loading}>
            <Download size={13} /> Télécharger le modèle
          </button>
        </div>

        {error && (
          <div className="alert critique" style={{ marginTop: 14 }}>
            <div className="alert-dot" />
            <div><strong>Import impossible</strong> — {error}</div>
          </div>
        )}

        {result && (
          <div style={{ marginTop: 14 }}>
            <div className="alert conforme">
              <div className="alert-dot" />
              <div>
                <strong>{result.company}</strong> — <span className="mono">{result.nb_moves}</span> écriture(s)
                au total dans le dossier ({' '}
                <span className="mono">{result.nb_moves_ajoutes}</span> ajoutée(s),{' '}
                <span className="mono">{result.nb_moves_mis_a_jour}</span> mise(s) à jour ), {' '}
                <span className="mono">{result.nb_partners}</span> tiers.
              </div>
            </div>

            {/* Les lignes écartées sont affichées, jamais tues : un import
                silencieusement partiel produirait un audit incomplet que
                personne ne saurait interpréter. */}
            {result.nb_lignes_ignorees > 0 && (
              <div className="alert vigilance" style={{ marginTop: 8 }}>
                <div className="alert-dot" />
                <div>
                  <strong>{result.nb_lignes_ignorees} ligne(s) ignorée(s)</strong> — le reste du fichier a bien été importé.
                  <ul style={{ margin: '6px 0 0 16px', fontSize: 12, lineHeight: 1.6 }}>
                    {result.warnings?.slice(0, 6).map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                </div>
              </div>
            )}

            {result.nb_lignes_ignorees === 0 && result.warnings?.length > 0 && (
              <div className="alert vigilance" style={{ marginTop: 8 }}>
                <div className="alert-dot" />
                <div>
                  <AlertTriangle size={13} style={{ verticalAlign: -2 }} /> Points de vigilance :
                  <ul style={{ margin: '6px 0 0 16px', fontSize: 12, lineHeight: 1.6 }}>
                    {result.warnings.slice(0, 6).map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                </div>
              </div>
            )}

            <div style={{ fontSize: 12.5, color: 'var(--ardoise)', marginTop: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
              <CheckCircle2 size={13} style={{ color: 'var(--conforme)' }} />
              Rendez-vous dans <strong>Audit</strong> pour lancer l'analyse sur ces données.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
