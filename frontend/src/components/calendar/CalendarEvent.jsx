import Badge from '../ui/Badge'
import { parseDate } from '../../utils/dates'

export default function CalendarEvent({ e }) {
  const dt = parseDate(e.date)
  const urgencyCls = e.urgency === 'critique' ? 'critique' : e.urgency === 'urgent' ? 'urgent' : e.urgency === 'normal' ? 'normal' : 'planifié'

  const statusCls = e.payment_status === 'paye' ? 'conforme' : e.payment_status === 'en_retard' ? 'critique' : 'vigilance'
  const statusLabel = e.payment_status === 'paye' ? '🟢 Payé (Odoo)' : e.payment_status === 'en_retard' ? '🔴 En retard' : '🟠 À venir'

  return (
    <div className="calendar-event">
      <div className={`event-bar ${urgencyCls}`} />
      <div className="event-inner">
        {dt && (
          <div className="event-date-col">
            <div className="event-day">{dt.day}</div>
            <div className="event-month">{dt.month}</div>
          </div>
        )}
        <div className="event-content">
          <div className="event-title" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span>{e.title}</span>
            {e.legal_article && (
              <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', background: 'var(--toile)', border: '1px solid var(--bordure)', padding: '1px 6px', borderRadius: 4, color: 'var(--seuil)' }}>
                {e.legal_article}
              </span>
            )}
            {e.doc_version && (
              <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', background: 'color-mix(in srgb, var(--seuil) 8%, transparent)', border: '1px solid color-mix(in srgb, var(--seuil) 20%, transparent)', padding: '1px 6px', borderRadius: 4, color: 'var(--ardoise)' }}>
                {e.doc_version}
              </span>
            )}
          </div>
          <div className="event-desc">{e.description}</div>
          {e.penalty && <div className="event-penalty">{e.penalty}</div>}
        </div>
        <div className="event-meta" style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
          <Badge cls={statusCls} dot>{statusLabel}</Badge>
          <div style={{ display: 'flex', gap: 4 }}>
            <Badge cls={urgencyCls === 'critique' ? 'critique' : urgencyCls === 'urgent' ? 'vigilance' : urgencyCls === 'normal' ? 'seuil' : 'conforme'}>
              {e.category}
            </Badge>
            <Badge cls="neutral">{e.urgency}</Badge>
          </div>
        </div>
      </div>
    </div>
  )
}
