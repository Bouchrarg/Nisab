# Nisab Mobile — espace dirigeant (Lot 4, optionnel)

App React Native (via Expo ) pour le rôle `dirigeant_pme` : 3 écrans en lecture
seule sur les endpoints déjà exposés par le backend, aucune route nouvelle.

## Lancer en local

1. Le backend doit tourner (`uvicorn app.main:app --reload` depuis `backend/`)
   et être **joignable depuis le téléphone** — `localhost` ne veut rien dire
   sur un appareil physique. Tant que le backend n'est pas déployé (Lot 1.3),
   le téléphone et la machine qui fait tourner uvicorn doivent être sur le
   **même Wi-Fi**, et `.env` doit pointer sur l'IP locale de la machine
   (`ipconfig` / `ifconfig`, pas `127.0.0.1`) :

   ```
   EXPO_PUBLIC_API_URL=http://<IP-locale>:8000
   ```

2. `npm install` 
3. `npx expo start` puis scanner le QR code avec l'app **Expo Go**
   (Android/iOS) sur le téléphone. Pas d'Android Studio, pas d'émulateur —
   c'est tout l'intérêt d'Expo Go pour ce lot.
4. Se connecter avec un compte `dirigeant_pme` existant (créé côté cabinet
   via `AppShell` → Invitations). Un compte collaborateur/cabinet/admin est
   refusé explicitement à la connexion : cette app n'a pas d'équivalent des
   vues cabinet.

## Écrans

| Écran | Endpoint | Donnée |
|---|---|---|
| Feux tricolores | `GET /dossiers/{id}/dashboard/summary` (tous les dossiers rattachés) | même logique 4 états que `DirigeantShell.jsx` côté web |
| Échéances | `GET /dossiers/{id}/calendar/events` | calendrier fiscal, non sourcé (`tax_calendar.py`) |
| Alertes critiques | `GET /dossiers/{id}/audit/resultat`, filtré `severity === 'rouge'` | alertes déjà persistées, jamais recalculées |

## Ce qui n'est délibérément pas fait ici

- Pas de notifications push (Firebase) — nécessiterait un compte FCM, une
  config native et un build EAS ; hors budget de ce lot.
- Pas de `react-navigation` — 3 écrans plats, routing manuel par `useState`
  dans `App.js`, même convention que `frontend/src/App.jsx` côté web.
- Pas d'action d'écriture (correction, relance d'audit, création de
  dossier) : ce rôle est en lecture seule sur le web aussi
  (`DirigeantShell.jsx`), l'app mobile ne fait qu'en reprendre le
  périmètre sur 3 écrans dédiés au lieu d'un seul.
