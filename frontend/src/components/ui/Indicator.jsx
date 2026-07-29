export default function Indicator({ label, sub, cls }) {
  return (
    <div className="indicator-card">
      <div className={`indicator-dot ${cls}`} />
      <div>
        <div className="indicator-label">{label}</div>
        {sub && <div className="indicator-sub">{sub}</div>}
      </div>
    </div>
  )
}
