import {
  LayoutDashboard, Shield, CalendarDays, MessageSquare, Link2, Settings,
} from 'lucide-react'

export const NAV = [
  { id: 'dashboard', label: 'Tableau de bord', Icon: LayoutDashboard, section: 'PILOTAGE' },
  { id: 'audit', label: 'Audit fiscal', Icon: Shield, section: null },
  { id: 'calendar', label: 'Calendrier fiscal', Icon: CalendarDays, section: null },
  { id: 'chat', label: 'Assistant IA', Icon: MessageSquare, section: 'ANALYSE' },
  { id: 'odoo', label: 'Synchronisation ERP', Icon: Link2, section: 'DONNÉES' },
  { id: 'admin', label: 'Administration', Icon: Settings, section: 'SYSTÈME' },
]

export const VIEW_TITLES = {
  dashboard: 'Tableau de bord',
  audit: 'Audit fiscal',
  calendar: 'Calendrier fiscal',
  chat: 'Assistant fiscal',
  odoo: 'Synchronisation ERP',
  admin: 'Administration du corpus',
}
