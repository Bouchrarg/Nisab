// Palette Nisab reprise de frontend/src/index.css:12-58 (tokens Direction D,
// portés le 17/08 depuis l'artifact validé) — même produit, deux runtimes.
// Pas de variables CSS en React Native, donc copie à la main plutôt qu'un
// import cross-projet (frontend et nisab-mobile ne partagent aucun bundler).
// Le web définit ces tons en oklch() ; converti ici en hex/rgba avec les
// mêmes L/C/H (RN ne résout pas oklch() de façon fiable sur ce runtime,
// cf. AGENTS.md). Si la palette web change, la répercuter ici à la main.
export const colors = {
  encre: '#221b17',
  ardoise: '#4d4641',
  sourdine: '#68625e',
  toile: '#f6ede2',
  bordure: '#e3ddd5',
  bordureDiscrete: '#ebe5de',
  surface: '#fffbf4',
  surface2: '#e8ded1',

  // Accent : bordeaux profond (remplace le bleu "seuil" d'avant Direction D)
  seuil: '#62081d',
  seuilDark: '#49000a',
  seuilSoft: 'rgba(98,8,29,0.10)',
  accentInk: '#fbf8f4', // texte sur fond accent plein (boutons pleins bordeaux)

  // Statuts — rouge/orange/vert francs (pas la version ocre/mate d'avant
  // Direction D, cf. le commentaire equivalent dans index.css:29-33)
  conforme: '#1e8347',
  conformeSoft: 'rgba(30,131,71,0.08)',
  vigilance: '#d76900',
  vigilanceSoft: 'rgba(215,105,0,0.12)',
  critique: '#c50220',
  critiqueSoft: 'rgba(197,2,32,0.09)',
}

// Le feu tricolore utilise 4 états, pas 3 — "gris" (indéterminé) ne doit
// jamais être confondu avec "vert" (conforme). Même règle que
// frontend/src/pages/DirigeantShell.jsx:23-29.
export const feuColors = {
  rouge: { fg: colors.critique, bg: colors.critiqueSoft },
  orange: { fg: colors.vigilance, bg: colors.vigilanceSoft },
  vert: { fg: colors.conforme, bg: colors.conformeSoft },
  gris: { fg: colors.sourdine, bg: colors.toile },
}

// Mêmes tons que .badge.* dans frontend/src/App.css:477-481 — réutilisé pour
// l'urgence des échéances (URGENCY_CLS de CabinetOverviewPage.jsx) et la
// sévérité des alertes. `bg` n'est plus consommé par Badge (Direction D :
// carré + texte neutre, plus de pilule colorée) mais reste ici documenté,
// certains écrans l'utilisent pour un fond de citation (ex. AlertesScreen).
export const badgeTones = {
  conforme: { fg: colors.conforme, bg: colors.conformeSoft },
  vigilance: { fg: colors.vigilance, bg: colors.vigilanceSoft },
  critique: { fg: colors.critique, bg: colors.critiqueSoft },
  seuil: { fg: colors.seuil, bg: colors.seuilSoft },
  neutral: { fg: colors.sourdine, bg: colors.toile },
}

// Polices Direction D (frontend/src/index.css:42-44) : IBM Plex Sans/Mono +
// Source Serif 4 pour les titres/gros chiffres. RN n'a pas de font-weight
// variable sur une police custom : chaque graisse est un fichier chargé à
// part (cf. App.js::useFonts) et sélectionné ici par nom, jamais par
// `fontWeight` en plus de `fontFamily` (le fallback système reprendrait la
// main sur certains graisses non résolues).
export const fonts = {
  sans: 'IBMPlexSans_400Regular',
  sansMedium: 'IBMPlexSans_500Medium',
  sansSemiBold: 'IBMPlexSans_600SemiBold',
  sansBold: 'IBMPlexSans_700Bold',
  mono: 'IBMPlexMono_400Regular',
  monoMedium: 'IBMPlexMono_500Medium',
  monoSemiBold: 'IBMPlexMono_600SemiBold',
  display: 'SourceSerif4_600SemiBold',
  displayBold: 'SourceSerif4_700Bold',
}

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 }

// --radius-sm/md valent 8px et --radius-card 10px côté web depuis Direction D
// (index.css:54-56) — resserré par rapport à l'ancien jeu de valeurs.
export const radius = { sm: 8, md: 8, card: 10, full: 999 }
