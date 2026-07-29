export default function Badge({ cls, children, dot = false }) {
  return (
    <span className={`badge ${cls}`}>
      {dot && <span className="badge-dot" style={{ background: 'currentColor' }} />}
      {children}
    </span>
  )
}
