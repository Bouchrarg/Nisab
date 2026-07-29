import { useEffect, useState } from 'react'
import { Info } from 'lucide-react'
import CalendarEvent from '../components/calendar/CalendarEvent'
import { API_URL } from '../config/api'

export default function CalendarPage() {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [tvaRegime, setTvaRegime] = useState('mensuel')
  const [regime, setRegime] = useState('normal')

  useEffect(() => {
    setLoading(true)
    fetch(`${API_URL}/calendar/events?regime=${regime}&tva_regime=${tvaRegime}`)
      .then((r) => r.json())
      .then((d) => {
        setEvents(d.events || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [tvaRegime, regime])

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-title">Calendrier fiscal</div>
          <div className="section-sub">
            Échéances calculées d'après le CGI marocain — les dates sont générées dynamiquement selon le régime fiscal sélectionné, sans données Odoo requises.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {['mensuel', 'trimestriel'].map((r) => (
            <button
              key={r}
              className={`btn btn-sm ${tvaRegime === r ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setTvaRegime(r)}
            >
              TVA {r}
            </button>
          ))}
          {['normal', 'simplifie'].map((r) => (
            <button
              key={r}
              className={`btn btn-sm ${regime === r ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setRegime(r)}
            >
              IS {r}
            </button>
          ))}
        </div>
      </div>

      <div className="alert info" style={{ marginBottom: 16 }}>
        <Info size={14} style={{ flexShrink: 0 }} />
        <div style={{ fontSize: 12 }}>
          Les échéances sont calculées automatiquement à partir de la date du jour et des règles du CGI 2026 (Art. 110, 170, 208). Elles ne dépendent pas des données Odoo.
        </div>
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
          <span className="spinner dark" style={{ width: 22, height: 22 }} />
        </div>
      ) : (
        <div className="calendar-list">
          {events.length === 0 ? (
            <div className="alert neutral">
              <div className="alert-dot" />Aucune échéance dans les 6 prochains mois.
            </div>
          ) : (
            events.map((e, i) => <CalendarEvent key={i} e={e} />)
          )}
        </div>
      )}
    </div>
  )
}
