// Anneau de score circulaire — seule exception documentée à la règle
// Direction D "statut = carré, jamais un anneau" (cf. GaugeSeuil.jsx pour
// la variante barre horizontale utilisée ailleurs). Demandé explicitement
// pour le résumé exécutif du tableau de bord : ce bloc doit se lire en un
// coup d'œil, avant même de lire le texte à côté — un cercle rempli au
// prorata du score porte plus vite cette information qu'un chiffre seul
// dans un carré plein.
//
// SVG plutôt que conic-gradient CSS : stroke-dasharray anime proprement
// (transition déjà posée en CSS) et reste net à n'importe quelle taille,
// contrairement à un dégradé conique dont l'anticrénelage du bord dépend
// du navigateur.
export default function GaugeRing({ score, cls, size = 64, strokeWidth = 6 }) {
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  // Borné [0,100] : un score hors bornes (ne devrait jamais arriver côté
  // API, mais un anneau qui déborde silencieusement serait plus trompeur
  // qu'un anneau plein ou vide.
  const clamped = Math.max(0, Math.min(100, score))
  const offset = circumference * (1 - clamped / 100)

  return (
    <div className="gauge-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle className="gauge-ring-track" cx={size / 2} cy={size / 2} r={radius} strokeWidth={strokeWidth} fill="none" />
        <circle
          className={`gauge-ring-fill ${cls}`}
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={strokeWidth}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          // Départ en haut (12h) plutôt que 3h (défaut SVG) — lecture
          // "horloge" plus naturelle pour un score de conformité.
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <div className={`gauge-ring-value ${cls}`}>{score}</div>
    </div>
  )
}
