const MONTHS_FR = ['jan', 'fév', 'mar', 'avr', 'mai', 'jun', 'jul', 'aoû', 'sep', 'oct', 'nov', 'déc']

export function parseDate(iso) {
  if (!iso) return null
  const d = new Date(iso)
  return { day: d.getDate(), month: MONTHS_FR[d.getMonth()], year: d.getFullYear() }
}
