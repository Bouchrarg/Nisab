#!/usr/bin/env node
// scripts/capture_screenshots.js
//
// Capture une DÉMO narrative du frontend (pas un inventaire mécanique de
// pages) : connexion → cabinet → un dossier vedette exploré en profondeur
// (audit, correction, assistant) → deux dossiers secondaires pour ce qu'ils
// apportent de spécifique (contraste "conforme", historique de simulation)
// → espace dirigeant → administration plateforme.
//
// Invariant de sécurité, respecté partout dans ce fichier : aucun clic sur
// un bouton qui relance un calcul long (audit, simulation) ou qui persiste
// une donnée non désirée (soumission d'un formulaire de démo). Concrètement,
// ne sont JAMAIS cliqués : "Lancer l'audit" / "Actualiser l'audit" /
// "Relancer l'analyse", "Lancer la simulation de contrôle", "Proposer une
// correction" (génère aussi un appel LLM), "Valider"/"Rejeter"/"Créer le
// brouillon dans Odoo"/"Enregistrer l'amendement" (workflow de correction),
// "Confirmer" (attribution d'accès), "Inviter" (envoi réel d'invitation), et
// aucun des deux formulaires de login/inscription de captureAuthPages()
// n'est soumis. Poser une question à l'assistant (copilote flottant ou
// onglet Assistant IA) EST autorisé et fait exprès un appel LLM — c'est
// différent d'un audit/simulation (secondes, pas minutes) et explicitement
// demandé pour la documentation.
//
// Pré-requis (deux terminaux séparés) :
//   1) backend : cd backend && uvicorn app.main:app --reload
//   2) frontend : cd frontend && npm run dev
//
// Lancement (depuis frontend/) :
//   node scripts/capture_screenshots.js
//
// Sorties dans <racine du repo>/screenshots/, numérotées dans l'ordre de
// capture (l'ordre EST la narration : les parcourir dans l'ordre raconte la
// démo de bout en bout).

import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT_DIR = path.join(__dirname, '..', '..', 'screenshots')
const FRONTEND_URL = process.env.NISAB_FRONTEND_URL || 'http://localhost:5173'
const VIEWPORT = { width: 1440, height: 900 }
// x2 par défaut : captures plus nettes pour des slides de soutenance.
const SCALE = Number(process.env.NISAB_SCREENSHOT_SCALE || 2)
// Une question à l'assistant appelle un vrai LLM (Groq/OpenRouter,
// embedding+retrieval+génération). En régime "chaud" ça répond en quelques
// secondes à ~30s, MAIS le tout premier appel après un redémarrage backend
// est beaucoup plus lent (constaté : >90s, probablement le modèle
// d'embeddings local — intfloat/multilingual-e5-base — chargé en mémoire de
// façon synchrone au premier usage, ce qui bloque tout le event loop uvicorn
// mono-process). Timeout large + les deux appels sont chacun protégés par
// leur propre try/catch dans captureCabinet() : un aléa LLM ne coûte que
// CETTE capture, jamais le reste de la démo.
const CHAT_TIMEOUT_MS = 300000

// ── Comptes de démo (fournis pour cette capture, pas des secrets prod) ──────
const ACCOUNTS = {
  cabinet: { email: 'rguibi.bouchra@ensam-casa.ma', password: 'testNisab' },
  dirigeant: { email: 'busrargrca@gmail.com', password: 'testColab' },
  plateforme: { email: 'bouchrarguibi2005@gmail.com', password: 'NisabAdmin' },
}

// UUID (pas le libellé) des 3 dossiers de démo — vérifiés en direct contre
// GET /dossiers le 20/08/2026 (curl, pas le front) : Nisab_demo = 10
// anomalies / 35 000 DH, Test Conforme = 0 anomalie, Atlas Négoce SARL = 8
// anomalies / 59 166,67 DH, les trois avec audit_status="done". Sélectionner
// par UUID (option value) plutôt que par raison_sociale (option label)
// élimine toute ambiguïté de libellé (accents, casse, doublons).
const DOSSIER_NISAB_DEMO = { slug: 'nisab-demo', id: 'a77e1eee-73fb-498d-920b-02336c5fd587' }
const DOSSIER_CONFORME = { slug: 'conforme', id: 'd7ebe786-8fd8-422c-9e43-6c70e7ba1b37' }
const DOSSIER_ATLAS = { slug: 'atlas-negoce', id: '8cc7e793-df58-46d0-915d-ec8227509bb7' }

// Miroir de PLATFORM_NAV (frontend/src/components/layout/PlatformSidebar.jsx).
const PLATFORM_VIEWS = [
  { id: 'overview', label: "Vue d'ensemble" },
  { id: 'organisations', label: 'Organisations' },
  { id: 'users', label: 'Utilisateurs' },
  { id: 'corpus', label: 'Corpus & Veille' },
]

let seq = 0
function nextName(...parts) {
  seq += 1
  const slug = parts
    .filter(Boolean)
    .join('-')
    .toLowerCase()
    .normalize('NFD').replace(/\p{Diacritic}/gu, '') // retire les accents
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return `${String(seq).padStart(2, '0')}-${slug}.png`
}

// Attend que la page se soit "installée" avant de capturer : réseau calme,
// plus aucun `.spinner` visible (classe utilisée de façon cohérente dans
// tout le front), puis un court délai pour laisser les transitions CSS se
// terminer. Ne fait jamais échouer le script : un timeout ici veut dire "on
// capture l'état actuel", pas "tout casse".
async function settle(page) {
  // Délai de grâce AVANT le check réseau : selectOption()/click() rendent la
  // main dès que le DOM event est géré, mais le useEffect React qui
  // déclenche le vrai fetch ne part qu'au commit suivant — sans ce délai,
  // waitForLoadState('networkidle') peut se déclarer "calme" avant même que
  // la requête ne parte (constaté en pratique sur le changement de dossier).
  await page.waitForTimeout(300)
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {})
  await page
    .waitForFunction(() => !document.querySelector('.spinner'), null, { timeout: 20000 })
    .catch(() => {})
  await page.waitForTimeout(400)
}

// L'app a un scroll INTERNE : `.page` (ou `.platform-admin-body`) est en
// overflow-y:auto sous un `.shell` en height:100vh + overflow:hidden — le
// <body> du document, lui, ne défile JAMAIS. `page.screenshot({fullPage:true})`
// ne connaît que le scroll du document : sans ce correctif, tout ce qui
// dépasse un écran de haut dans `.page` était invisible sur la capture, SANS
// AUCUNE ERREUR pour le signaler. On neutralise cette contrainte de hauteur
// juste avant chaque capture pleine page (recalculé à chaque fois : la vue
// suivante peut avoir un DOM différent) pour que le document s'étire
// vraiment et que fullPage capture tout le contenu, jusqu'en bas.
async function expandForFullCapture(page) {
  await page.evaluate(() => {
    const chains = [
      ['.shell', '.main-content', '.page'],
      ['.platform-admin-shell', '.platform-admin-main', '.platform-admin-body'],
    ]
    for (const selectors of chains) {
      for (const sel of selectors) {
        const el = document.querySelector(sel)
        if (el) {
          el.style.height = 'auto'
          el.style.maxHeight = 'none'
          el.style.overflow = 'visible'
        }
      }
    }
  }).catch(() => {})
}

async function shootWith(page, fullPage, ...nameParts) {
  const file = nextName(...nameParts)
  await settle(page)
  if (fullPage) await expandForFullCapture(page)
  await page.screenshot({ path: path.join(OUT_DIR, file), fullPage })
  console.log(`  ✓ ${file}`)
}
// fullPage : capture tout le contenu réel de la page (voir expandForFullCapture).
async function shoot(page, ...nameParts) { return shootWith(page, true, ...nameParts) }
// viewport-only : réservé au copilote flottant (position fixed) — il est de
// toute façon déjà visible à l'écran, pas besoin d'étirer le document pour lui.
async function shootViewport(page, ...nameParts) { return shootWith(page, false, ...nameParts) }

// Survole un élément et capture — démontre l'effet hover (.dossier-card,
// .nav-item — cf. App.css) SANS cliquer. Utilisé une seule fois dans toute
// la démo (vue d'ensemble) : le principe est démontré, pas la peine de le
// répéter sur chaque page.
async function hoverShoot(page, locator, ...nameParts) {
  if ((await locator.count()) === 0) {
    console.warn(`  ⚠ cible de hover introuvable (${nameParts.join('/')})`)
    return
  }
  await locator.first().hover()
  await page.waitForTimeout(150)
  await shoot(page, ...nameParts)
}

// Seule fonction qui clique dans le contenu de l'app pour NAVIGUER — et
// uniquement sur un item de la sidebar (.nav-item). Les clics d'expansion
// (anomalie, correction, simulation, etc.) sont faits séparément, ligne par
// ligne, dans les fonctions dédiées ci-dessous, jamais sur un bouton
// d'action qui recalculerait quelque chose.
async function goToNav(page, label) {
  const item = page.locator('.sidebar-nav .nav-item', { hasText: label })
  if ((await item.count()) === 0) return false
  await item.first().click()
  return true
}

async function login(page, { email, password }, readySelector) {
  await page.goto(FRONTEND_URL, { waitUntil: 'domcontentloaded' })
  await page.fill('#email', email)
  await page.fill('#password', password)
  await page.click('button.auth-submit')
  try {
    await page.waitForSelector(readySelector, { timeout: 60000 })
  } catch (e) {
    const alertText = await page.locator('.auth-alert').textContent().catch(() => null)
    throw new Error(
      `Connexion échouée pour ${email} (sélecteur "${readySelector}" jamais apparu).`
      + (alertText ? ` Message affiché : ${alertText.trim()}` : '')
    )
  }
  await settle(page)
}

// Bascule sur un dossier PAR UUID (pas par libellé) et attend les deux
// requêtes séquentielles que loadDashboard() (App.jsx) déclenche à ce
// changement : /dashboard/summary puis, seulement si son résultat indique
// des données présentes, /audit/resultat. `settle()` seul ne suffisait pas
// ici : entre les deux requêtes, le réseau peut paraître "calme" à
// Playwright pendant quelques ms, ce qui lui faisait déclarer la page prête
// avant que la 2e requête ne soit même partie.
async function selectDossier(page, dossierId) {
  const options = await page.$$eval('.dossier-switcher select option', (els) => els.map((o) => o.value))
  if (!options.includes(dossierId)) {
    console.warn(`  ⚠ dossier ${dossierId} introuvable dans le switcher (options: ${options.join(', ') || 'aucune'})`)
    return false
  }

  const summaryWait = page
    .waitForResponse(
      (res) => res.request().method() === 'GET' && res.url().includes(`/dossiers/${dossierId}/dashboard/summary`),
      { timeout: 20000 }
    )
    .catch(() => null)

  await page.selectOption('.dossier-switcher select', { value: dossierId })
  const summaryRes = await summaryWait
  if (!summaryRes) {
    console.warn(`  ⚠ /dashboard/summary jamais reçu pour ${dossierId} (timeout 20s)`)
  } else {
    const body = await summaryRes.json().catch(() => null)
    if (body && body.status !== 'no_data' && body.company) {
      await page
        .waitForResponse((res) => res.url().includes(`/dossiers/${dossierId}/audit/resultat`), { timeout: 10000 })
        .catch(() => console.warn(`  ⚠ /audit/resultat jamais reçu pour ${dossierId} (données pourtant chargées)`))
    }
  }

  await settle(page)
  return true
}

// ── Démonstrations d'interaction (une par écran concerné) ──────────────────

// Ouvre le copilote flottant, pose une question de suggestion CONTEXTUELLE
// AU DOSSIER (le dossier actif doit avoir des données chargées, sinon le
// fond de l'écran contredit visuellement la question posée), attend la
// vraie réponse, capture, puis referme (le composant reste monté d'une vue
// à l'autre, cf. COPILOT_VIEWS dans App.jsx).
async function captureCopilotQuestion(page, dossierSlug) {
  const fab = page.locator('#copilot-fab-btn')
  if ((await fab.count()) === 0) return
  await fab.click()
  await page.waitForTimeout(400) // transition d'ouverture du tiroir
  const suggestion = page.locator('.copilot-suggestion').first()
  if ((await suggestion.count()) === 0) {
    console.warn('  ⚠ pas de suggestion sur le copilote flottant')
    await fab.click()
    return
  }
  const respWait = page
    .waitForResponse((res) => res.request().method() === 'POST' && res.url().includes('/chat'), { timeout: CHAT_TIMEOUT_MS })
    .catch(() => null)
  await suggestion.click()
  const res = await respWait
  if (!res) console.warn(`  ⚠ le copilote flottant n'a pas répondu dans le délai (${CHAT_TIMEOUT_MS}ms)`)
  await page.waitForTimeout(600)
  await shootViewport(page, 'copilot-question', dossierSlug)
  await fab.click()
  await page.waitForTimeout(300)
}

// Pose une question depuis l'onglet Assistant IA plein écran (page à part,
// pas le copilote flottant) — appelée alors que le dossier actif a des
// données chargées (le switcher en haut de page doit montrer un dossier
// avec des données, pas "Données non importées", pour ne pas paraître
// contredire la question). Clique ensuite une source citée pour montrer le
// panneau "article de loi complet".
async function captureChatQuestion(page) {
  const suggestion = page.locator('.suggestion').first()
  if ((await suggestion.count()) === 0) {
    console.warn('  ⚠ pas de suggestion sur la page Assistant IA')
    return
  }
  const respWait = page
    .waitForResponse((res) => res.request().method() === 'POST' && res.url().includes('/chat'), { timeout: CHAT_TIMEOUT_MS })
    .catch(() => null)
  await suggestion.click()
  const res = await respWait
  if (!res) console.warn(`  ⚠ l'assistant (onglet) n'a pas répondu dans le délai (${CHAT_TIMEOUT_MS}ms)`)
  await page.waitForTimeout(600)
  await shoot(page, 'chat-reponse')

  const sourcePill = page.locator('.source-pill').first()
  if ((await sourcePill.count()) > 0) {
    await sourcePill.click()
    await shoot(page, 'chat-article-cite')
  }
}

// Déplie une anomalie avec un montant CHIFFRÉ (pas "non chiffrable") et des
// citations — le cas le plus démonstratif du moteur regles_montant + RAG.
// Le bouton "Proposer une correction" devient visible mais n'est PAS cliqué
// (relancerait le LLM de correction).
async function captureFindingDetail(page, dossierSlug) {
  const head = page
    .locator('.finding-head', { hasText: 'Charge réglée en espèces au-delà de la limite déductible' })
    .first()
  if ((await head.count()) === 0) {
    console.warn('  ⚠ anomalie de démonstration introuvable sur la page Audit')
    return
  }
  await head.click()
  await shoot(page, 'audit-anomalie-detail', dossierSlug)
}

// Sélectionne une correction "en_attente" existante dans le master/détail —
// simple GET, aucune génération. Les boutons Valider/Rejeter/Créer le
// brouillon deviennent visibles mais ne sont PAS cliqués (workflow réel,
// changerait un statut en base).
async function captureCorrectionDetail(page, dossierSlug) {
  const row = page
    .locator('.card table tbody tr', { hasText: 'Demander une facture régulière au fournisseur' })
    .first()
  if ((await row.count()) === 0) {
    console.warn('  ⚠ correction de démonstration introuvable')
    return
  }
  // Attente explicite du GET /propositions/{id} déclenché par ouvrir() —
  // même raison que selectDossier() : settle() seul ne garantit pas que
  // CETTE requête précise a fini avant la capture.
  const respWait = page.waitForResponse((res) => res.url().includes('/propositions/'), { timeout: 15000 }).catch(() => null)
  await row.click()
  const res = await respWait
  if (!res) console.warn('  ⚠ /propositions/{id} jamais reçu après le clic sur la correction')
  await shoot(page, 'corrections-detail', dossierSlug)
}

// Déplie l'historique des simulations (2 rapports existants sur ce
// dossier), bascule sur l'AUTRE rapport via "Voir" (GET, pas une nouvelle
// simulation), puis déplie un thème pour montrer l'argumentaire de défense.
async function captureSimulationDetail(page, dossierSlug) {
  const historyToggle = page.locator('span', { hasText: 'Historique des simulations' }).first()
  if ((await historyToggle.count()) === 0) {
    console.warn('  ⚠ historique de simulation introuvable')
    return
  }
  await historyToggle.click()
  await shoot(page, 'simulation-historique', dossierSlug)

  const voirBtn = page.locator('button:not([disabled])', { hasText: 'Voir' }).first()
  if ((await voirBtn.count()) > 0) {
    const respWait = page.waitForResponse((res) => res.url().includes('/simulations/'), { timeout: 15000 }).catch(() => null)
    await voirBtn.click()
    await respWait
    await shoot(page, 'simulation-autre-rapport', dossierSlug)
  }

  const theme = page.locator('.card-body', { hasText: 'anomalie(s) liée(s)' }).first()
  if ((await theme.count()) > 0) {
    await theme.click()
    await shoot(page, 'simulation-theme-detail', dossierSlug)
  }
}

// Remplit le formulaire d'invitation SANS l'envoyer (un vrai envoi créerait
// une invitation persistée en base pour une adresse factice), montre aussi
// le comportement conditionnel du champ "Niveau d'accès" sur le rôle
// dirigeant_pme, puis ouvre (sans confirmer) le sous-formulaire d'attribution
// de dossier sur le premier membre.
async function captureInvitationsWorkflow(page) {
  const emailInput = page.locator('form.dossier-create-card input[type="email"]')
  if ((await emailInput.count()) === 0) return
  await emailInput.fill('collaborateur.demo@example.com')
  await shoot(page, 'invitations-formulaire-rempli')

  const roleSelect = page.locator('form.dossier-create-card select').first()
  if ((await roleSelect.count()) > 0) {
    await roleSelect.selectOption('dirigeant_pme')
    await shoot(page, 'invitations-role-dirigeant')
  }

  const assignBtn = page.locator('button', { hasText: 'Assigner' }).first()
  if ((await assignBtn.count()) > 0) {
    await assignBtn.click()
    await shoot(page, 'invitations-assigner-dossier')
  }
}

// ── Chapitre 1 : pages login / inscription — contexte à part, jamais soumis ─
async function captureAuthPages(browser) {
  console.log('\n== 1. Connexion / inscription ==')
  const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: SCALE })
  const page = await context.newPage()
  await page.goto(FRONTEND_URL, { waitUntil: 'domcontentloaded' })
  await settle(page)
  await shoot(page, 'login-vide')

  await page.fill('#email', ACCOUNTS.cabinet.email)
  await page.fill('#password', ACCOUNTS.cabinet.password)
  await hoverShoot(page, page.locator('button.auth-submit'), 'login-rempli-hover')

  // Bascule vers inscription — champs de démonstration UNIQUEMENT, jamais
  // soumis (créer une vraie organisation ici polluerait la base).
  await page.click('button.auth-switch')
  await settle(page)
  await page.fill('#nomOrganisation', 'Cabinet Démo Capture')
  await page.fill('#email', 'demo.capture@example.com')
  await page.fill('#password', 'CaptureDemo123')
  await shoot(page, 'inscription-remplie')

  await context.close()
}

// ── Chapitre 2 à 6 : shell cabinet, une seule session/dossier-switcher ──────
async function captureCabinet(browser) {
  const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: SCALE })
  const page = await context.newPage()
  await login(page, ACCOUNTS.cabinet, '.sidebar-nav')

  // -- 2. Vue d'ensemble du cabinet (portefeuille multi-dossiers) --
  console.log('\n== 2. Vue d\'ensemble du cabinet ==')
  if (await goToNav(page, "Vue d'ensemble")) {
    await shoot(page, 'overview')
    await hoverShoot(page, page.locator('.dossier-card').first(), 'overview-hover-dossier')
    await hoverShoot(page, page.locator('.sidebar-nav .nav-item', { hasText: 'Audit fiscal' }), 'overview-hover-nav')
  }

  // -- 3. Mise en place cabinet : ERP, équipe, profil --
  console.log('\n== 3. Mise en place (ERP, équipe, profil) ==')
  if (await goToNav(page, 'Synchronisation ERP')) await shoot(page, 'odoo')
  if (await goToNav(page, 'Équipe')) await captureInvitationsWorkflow(page)
  if (await goToNav(page, 'Mon profil')) await shoot(page, 'profile')

  // -- 4. Dossier vedette : Nisab_demo (anomalies critiques) — le cœur de la
  //    démo, exploré en profondeur : audit → anomalie → correction →
  //    calendrier → veille → assistant (sur CE dossier, données chargées). --
  console.log('\n== 4. Dossier vedette — Nisab_demo (anomalies critiques) ==')
  const heroOk = await selectDossier(page, DOSSIER_NISAB_DEMO.id)
  if (heroOk) {
    if (await goToNav(page, 'Tableau de bord')) {
      await shoot(page, 'dashboard', DOSSIER_NISAB_DEMO.slug)
      try {
        await captureCopilotQuestion(page, DOSSIER_NISAB_DEMO.slug)
      } catch (e) {
        console.warn(`  ⚠ copilote flottant échoué, ignoré (${e.message})`)
      }
    }
    if (await goToNav(page, 'Audit fiscal')) {
      await shoot(page, 'audit', DOSSIER_NISAB_DEMO.slug)
      await captureFindingDetail(page, DOSSIER_NISAB_DEMO.slug)
    }
    if (await goToNav(page, 'Corrections')) {
      await shoot(page, 'corrections', DOSSIER_NISAB_DEMO.slug)
      await captureCorrectionDetail(page, DOSSIER_NISAB_DEMO.slug)
    }
    if (await goToNav(page, 'Calendrier fiscal')) await shoot(page, 'calendar', DOSSIER_NISAB_DEMO.slug)
    if (await goToNav(page, 'Veille fiscale')) await shoot(page, 'veille', DOSSIER_NISAB_DEMO.slug)
    // Assistant en dernier sur ce dossier : le switcher affiche encore
    // Nisab_demo (données chargées), donc le fond de page reste cohérent
    // avec la question posée — plus la contradiction "no data" constatée
    // quand ce test tournait sur le dossier par défaut (testServices, vide).
    if (await goToNav(page, 'Assistant IA')) {
      try {
        await captureChatQuestion(page)
      } catch (e) {
        console.warn(`  ⚠ assistant (onglet) échoué, ignoré (${e.message})`)
      }
    }
  }

  // -- 5. Dossier conforme : juste le contraste (0 anomalie), pas les 6 vues --
  console.log('\n== 5. Dossier conforme — contraste ==')
  if (await selectDossier(page, DOSSIER_CONFORME.id)) {
    if (await goToNav(page, 'Audit fiscal')) await shoot(page, 'audit', DOSSIER_CONFORME.slug)
  }

  // -- 6. Dossier Atlas Négoce SARL : uniquement pour l'historique de
  //    simulation (2 rapports en base, le seul dossier qui le permet). --
  console.log('\n== 6. Dossier Atlas Négoce SARL — simulation de contrôle ==')
  if (await selectDossier(page, DOSSIER_ATLAS.id)) {
    if (await goToNav(page, 'Audit fiscal')) await shoot(page, 'audit', DOSSIER_ATLAS.slug)
    if (await goToNav(page, 'Simulation de contrôle')) {
      await shoot(page, 'simulation', DOSSIER_ATLAS.slug)
      await captureSimulationDetail(page, DOSSIER_ATLAS.slug)
    }
  }

  await context.close()
}

// ── Chapitre 7 : espace dirigeant (vue client, lecture seule) ──────────────
async function captureDirigeant(browser) {
  console.log('\n== 7. Espace dirigeant (dirigeant_pme) ==')
  const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: SCALE })
  const page = await context.newPage()
  await login(page, ACCOUNTS.dirigeant, 'text=Votre situation fiscale')
  await shoot(page, 'dirigeant', 'dashboard')

  // Le bouton "Mon profil" est le 1er <button> du header (avant "Se
  // déconnecter") — pas de sélecteur stable dispo car son libellé est
  // dynamique (nom/email de l'utilisateur), cf. DirigeantShell.jsx.
  await page.locator('header button').first().click()
  await shoot(page, 'dirigeant', 'profile')

  await context.close()
}

// ── Chapitre 8 : administration plateforme (coulisses) ──────────────────────
async function capturePlatform(browser) {
  console.log('\n== 8. Administration plateforme (admin_plateforme) ==')
  const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: SCALE })
  const page = await context.newPage()
  await login(page, ACCOUNTS.plateforme, '.platform-admin-shell')

  for (const view of PLATFORM_VIEWS) {
    const found = await goToNav(page, view.label)
    if (!found) {
      console.warn(`  ⚠ vue "${view.label}" introuvable, ignorée`)
      continue
    }
    await shoot(page, 'platform', view.id)
  }

  await context.close()
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true })
  console.log(`Sortie : ${OUT_DIR}`)
  console.log(`Frontend attendu sur : ${FRONTEND_URL}`)

  const browser = await chromium.launch()
  try {
    await captureAuthPages(browser)
    await captureCabinet(browser)
    await captureDirigeant(browser)
    await capturePlatform(browser)
  } finally {
    await browser.close()
  }

  console.log(`\nTerminé : ${seq} capture(s) écrite(s) dans ${OUT_DIR}`)
}

main().catch((e) => {
  console.error('\nÉchec du script de capture :', e.message)
  process.exit(1)
})
