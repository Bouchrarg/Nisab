# Cahier des charges — Nisab

> Version condensée à usage interne. Document source complet
> disponible séparément (version PDF/Word remise par l'encadrant).

## Sujet
Conception et développement d'une plateforme SaaS de copilote fiscal par IA,
ancrée sur le droit fiscal marocain, branchée sur les données réelles de
l'entreprise. Détecte erreurs et risques, répond avec citations, prépare au
contrôle. Cible: cabinets comptables + PME marocaines.

- Projet: Nisab — Modèle: Tax-Copilot-as-a-Service
- Périmètre: MVP — Durée: 2 mois
- Organisme d'accueil: IAAI Academy

## Contexte & objectif
IA ancrée sur le droit fiscal marocain (CGI, loi de finances, notes
circulaires DGI), citation systématique obligatoire. Objectif du stage: un
MVP fonctionnel de défense fiscale. Le volet financement est explicitement
un Lot 2.

## Périmètre
- Géographie: Maroc, fiscalité de l'entreprise
- Langues (v1): français et arabe (darija pour l'assistant conversationnel)
- Secteurs: tous (TPE/PME)
- Utilisateurs: cabinets comptables + dirigeants de PME (multi-tenant)
- Canaux: app web (cabinet) + app mobile (dirigeant, alertes) + notifications
  WhatsApp/e-mail. Back-end commun (API) + connecteurs comptables.

## Les 7 modules fonctionnels (MVP)
1. **Ingestion & données** — connexion logiciel comptable + import
   (balance, factures, déclarations), réconciliation, détection des pièces
   manquantes.
2. **Assistant fiscal sourcé** — réponses en langage naturel (TVA, IS, IR,
   CNSS) avec citation systématique de l'article/note (anti-hallucination).
3. **Détection erreurs & risques** — analyse des données au regard du
   corpus: charges non déductibles, incohérences; chiffrage de l'exposition
   et priorisation.
4. **Simulation de contrôle** — rejoue les points examinés par un
   inspecteur; produit rapport + plan de remédiation (rien n'est transmis
   à la DGI).
5. **Pilotage des échéances** — calendrier TVA/IS/IR/CNSS (SIMPL), alertes
   anti-majoration personnalisées.
6. **Veille personnalisée** — lecture loi de finances + notes DGI,
   signalement de l'impact sur le dossier avec action à mener.
7. **Espaces & multi-tenant** — vue cabinet multi-dossiers + vue dirigeant
   simplifiée (feux tricolores), comptes, rôles, isolation des données.

## Contraintes techniques (imposées)
- IA via API d'un LLM (aucun modèle à entraîner) + RAG sur corpus fiscal
  marocain structuré et versionné par exercice — réponses uniquement
  sourcées.
- Connecteurs logiciels comptables (Sage, Odoo...) + import fichiers/OCR:
  se brancher sur l'existant, ne pas le refaire.
- Multi-tenant, isolation stricte des données; confidentialité et
  hébergement conformes (loi 09-08, CNDP).
- Anti-hallucination = cœur produit: zones grises renvoyées à l'expert.
- Back-end commun (API), base relationnelle; stack et hébergement à valider
  avec l'encadrant.

## Hors périmètre v1 (réservé Lot 2)
Score de finançabilité / dossier de crédit Tamwilcom; connexion directe
DGI/SIMPL et bancaire; télédéclaration automatique; conseil juridique
réglementé.

## Livrables attendus
- Code source documenté et versionné (Git)
- Plateforme déployée: app web + app mobile + corpus fiscal v1 (démo)
- Documentation technique (installation, architecture, BD, API)
- Rapport de stage

## Planning indicatif (cahier des charges initial)
- **Mois 1**: back-end (API), base de données, corpus fiscal structuré
  (CGI, loi de finances, notes DGI), assistant sourcé (RAG), ingestion et
  connexion des données, comptes/multi-tenant.
- **Mois 2**: détection erreurs et risques, simulation de contrôle,
  pilotage des échéances, veille personnalisée, application mobile,
  déploiement et finitions.

> Ce planning "Mois 1 / Mois 2" du cahier des charges a été affiné en un
> découpage plus fin à 9 phases côté implémentation — voir
> `docs/implementation-plan.md`.
