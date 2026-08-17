// Direction D : statut = carré plein + libellé texte, jamais un badge-pilule
// coloré (motif jugé "trop IA" par l'utilisatrice). Le carré porte la
// couleur du statut (.badge-dot, coloré via .badge.<cls> en CSS), le texte
// reste toujours de l'encre neutre — cf. App.css.
// `small` : variante pour les endroits où le badge est une info secondaire
// dans une liste (catégorie d'échéance à côté d'un titre qui doit dominer),
// pas le signal principal de la ligne.
export default function Badge({ cls, children, small = false }) {
  return (
    <span className={`badge ${cls}${small ? ' badge-sm' : ''}`}>
      <span className="badge-dot" />
      {children}
    </span>
  )
}
