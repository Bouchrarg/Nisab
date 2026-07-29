import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import Badge from '../ui/Badge'
import OdooPathBreadcrumb from './OdooPathBreadcrumb'
import { severityToCls } from '../../utils/severity'

export default function FindingCard({ f }) {
  const [open, setOpen] = useState(false)
  const cls = severityToCls(f.severity)
  const severityLabel = cls === 'critique' ? 'Critique' : cls === 'vigilance' ? 'Modéré' : 'Faible'

  return (
    <div className="finding">
      <div className="finding-inner">
        <div className={`finding-bar ${cls}`} />
        <div className="finding-main">

          <div className="finding-head" onClick={() => setOpen(o => !o)} style={{ cursor: 'pointer' }}>
            <div className="finding-left">
              <Badge cls={cls}>{severityLabel}</Badge>
              <span className="finding-title">{f.title || 'Comptabilité non conforme'}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {f.amount_risk > 0 && (
                <span className="finding-amount mono">−{Number(f.amount_risk).toLocaleString('fr-MA')} DH</span>
              )}
              {open ? <ChevronUp size={14} color="var(--sourdine)" /> : <ChevronDown size={14} color="var(--sourdine)" />}
            </div>
          </div>

          {open && (
            <div className="finding-body">

              {(f.invoice || f.partner || f.date) && (
                <div style={{ background: 'var(--toile)', border: '1px solid var(--bordure)', borderRadius: 6, padding: '10px 14px', marginBottom: 12 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--sourdine)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>
                    Écriture comptable auditée
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px,1fr))', gap: '6px 16px' }}>
                    {f.invoice && (
                      <div>
                        <div style={{ fontSize: 10, color: 'var(--sourdine)' }}>N° Pièce</div>
                        <div style={{ fontSize: 12.5, fontFamily: 'var(--font-mono)', color: 'var(--encre)', fontWeight: 600 }}>{f.invoice}</div>
                      </div>
                    )}
                    {f.partner && (
                      <div>
                        <div style={{ fontSize: 10, color: 'var(--sourdine)' }}>Fournisseur / Tiers</div>
                        <div style={{ fontSize: 12.5, color: 'var(--encre)' }}>{f.partner}</div>
                      </div>
                    )}
                    {f.date && (
                      <div>
                        <div style={{ fontSize: 10, color: 'var(--sourdine)' }}>Date</div>
                        <div style={{ fontSize: 12.5, fontFamily: 'var(--font-mono)', color: 'var(--encre)' }}>{f.date}</div>
                      </div>
                    )}
                    {f.amount_risk > 0 && (
                      <div>
                        <div style={{ fontSize: 10, color: 'var(--sourdine)' }}>Exposition estimée</div>
                        <div style={{ fontSize: 12.5, fontFamily: 'var(--font-mono)', color: 'var(--critique)', fontWeight: 700 }}>
                          {Number(f.amount_risk).toLocaleString('fr-MA')} DH
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {f.reference_cgi && (
                <div style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--sourdine)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 4 }}>
                    Fondement légal (CGI 2026)
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <span style={{
                      fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--seuil)',
                      background: 'color-mix(in srgb, var(--seuil) 10%, transparent)',
                      border: '1px solid color-mix(in srgb, var(--seuil) 25%, transparent)',
                      borderRadius: 4, padding: '2px 8px', fontWeight: 600
                    }}>{f.reference_cgi}</span>
                    {f.rag_sources && f.rag_sources.length > 0 && f.rag_sources
                      .filter(s => s !== f.reference_cgi)
                      .map((s, i) => (
                        <span key={i} style={{
                          fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--ardoise)',
                          background: 'var(--toile)', border: '1px solid var(--bordure)',
                          borderRadius: 4, padding: '2px 6px'
                        }}>{s}</span>
                      ))
                    }
                  </div>
                </div>
              )}

              {f.description && (
                <div style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--sourdine)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 4 }}>
                    Constat
                  </div>
                  <div style={{ fontSize: 12.5, color: 'var(--ardoise)', lineHeight: 1.6 }}>{f.description}</div>
                </div>
              )}

              {f.recommendation && (
                <div style={{
                  background: 'color-mix(in srgb, var(--seuil) 6%, transparent)',
                  border: '1px solid color-mix(in srgb, var(--seuil) 20%, transparent)',
                  borderRadius: 6, padding: '8px 12px',
                }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--seuil)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 4 }}>
                    Recommandation
                  </div>
                  <div style={{ fontSize: 12.5, color: 'var(--ardoise)', lineHeight: 1.55 }}>{f.recommendation}</div>
                </div>
              )}

              {f.odoo_path && (
                <OdooPathBreadcrumb path={f.odoo_path} />
              )}

            </div>
          )}

        </div>
      </div>
    </div>
  )
}
