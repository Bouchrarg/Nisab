export function severityToCls(s) {
  if (s === 'rouge') return 'critique'
  if (s === 'orange') return 'vigilance'
  return 'conforme'
}
