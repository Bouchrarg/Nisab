export default function OdooPathBreadcrumb({ path }) {
  if (!path) return null
  return (
    <div className="odoo-path-breadcrumb">
      <span className="odoo-path-text">
        {path.section} <span className="odoo-path-sep">›</span>{' '}
        <strong className="odoo-path-record">{path.record_name}</strong>
      </span>
    </div>
  )
}
