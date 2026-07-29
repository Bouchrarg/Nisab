export default function GaugeSeuil({ label, score, threshold = 70, className = '' }) {
  const cls = score >= threshold ? 'conforme' : score >= threshold * 0.75 ? 'vigilance' : 'critique'
  return (
    <div className={`gauge-wrap ${className}`}>
      <div className="gauge-header">
        <span className="gauge-label">{label}</span>
        <span className={`gauge-score mono ${cls}`}>{score}<span style={{ color: 'var(--sourdine)', fontSize: 12 }}>/100</span></span>
      </div>
      <div className="gauge-track">
        <div className={`gauge-fill ${cls}`} style={{ width: `${score}%` }} />
        <div className="gauge-threshold" style={{ left: `${threshold}%` }} />
      </div>
      <div className="gauge-threshold-label">
        <span style={{ position: 'absolute', left: `${threshold}%`, transform: 'translateX(-50%)' }}>
          seuil {threshold}
        </span>
      </div>
    </div>
  )
}
