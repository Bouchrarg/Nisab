// Palette Nisab reprise telle quelle de frontend/src/index.css:6-25 — même
// produit, deux runtimes. Pas de variables CSS en React Native, donc copie
// à la main plutôt qu'un import cross-projet (frontend et nisab-mobile ne
// partagent aucun bundler). Si la palette web change, la répercuter ici.
export const colors = {
  encre: '#16181D',
  ardoise: '#4B5163',
  sourdine: '#6B7280',
  toile: '#F5F6F8',
  bordure: '#E3E6EB',
  bordureDiscrete: '#EBEDF1',
  surface: '#FFFFFF',

  seuil: '#2451D6',
  seuilDark: '#1B3FA8',
  seuilSoft: '#EAF0FE',

  conforme: '#1D8A4C',
  conformeSoft: '#E7F6EC',
  vigilance: '#C2670C',
  vigilanceSoft: '#FDF1E1',
  critique: '#C0281C',
  critiqueSoft: '#FBEAE9',
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

// Mêmes tons que .badge.* dans frontend/src/App.css:380-384 — réutilisé pour
// l'urgence des échéances (URGENCY_CLS de CabinetOverviewPage.jsx) et la
// sévérité des alertes.
export const badgeTones = {
  conforme: { fg: colors.conforme, bg: colors.conformeSoft },
  vigilance: { fg: colors.vigilance, bg: colors.vigilanceSoft },
  critique: { fg: colors.critique, bg: colors.critiqueSoft },
  seuil: { fg: colors.seuil, bg: colors.seuilSoft },
  neutral: { fg: colors.ardoise, bg: colors.toile },
}

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 }

export const radius = { sm: 6, md: 8, card: 12, full: 999 }
