import {
  LayoutGrid, LayoutDashboard, Shield, ClipboardCheck, Gavel, CalendarDays, MessageSquare, Link2,
  UserCircle, Users, BellRing,
} from 'lucide-react'

// NOTE : 'admin' n'est pas ici — c'est un espace séparé réservé au rôle
// admin_plateforme (voir PlatformAdminShell dans App.jsx).
// `roles` (optionnel) restreint l'entrée à certains rôles ; absent = tout
// le monde dans le shell cabinet la voit.
export const NAV = [
  { id: 'overview', label: "Vue d'ensemble", Icon: LayoutGrid, section: 'CABINET' },
  { id: 'dashboard', label: 'Tableau de bord', Icon: LayoutDashboard, section: 'PILOTAGE' },
  { id: 'audit', label: 'Audit fiscal', Icon: Shield, section: null },
  { id: 'corrections', label: 'Corrections', Icon: ClipboardCheck, section: null },
  { id: 'simulation', label: 'Simulation de contrôle', Icon: Gavel, section: null },
  { id: 'calendar', label: 'Calendrier fiscal', Icon: CalendarDays, section: null },
  { id: 'chat', label: 'Assistant IA', Icon: MessageSquare, section: 'ANALYSE' },
  { id: 'veille', label: 'Veille fiscale', Icon: BellRing, section: null },
  { id: 'odoo', label: 'Synchronisation ERP', Icon: Link2, section: 'DONNÉES' },
  { id: 'invitations', label: 'Équipe', Icon: Users, section: 'COMPTE', roles: ['admin_cabinet'] },
  { id: 'profile', label: 'Mon profil', Icon: UserCircle, section: 'COMPTE' },
]

export const VIEW_TITLES = {
  overview: "Vue d'ensemble du cabinet",
  dashboard: 'Tableau de bord',
  audit: 'Audit fiscal',
  corrections: 'Corrections proposées',
  simulation: 'Simulation de contrôle',
  calendar: 'Calendrier fiscal',
  chat: 'Assistant fiscal',
  veille: 'Veille fiscale',
  odoo: 'Synchronisation ERP',
  invitations: 'Équipe',
  profile: 'Mon profil',
  admin: 'Administration du corpus',
}
