# Expo HAS CHANGED

Read the exact versioned docs at https://docs.expo.dev/versions/v54.0.0/ before writing any code.

Le projet a été rétrogradé du SDK 57 (pris par erreur via `create-expo-app@latest`,
qui suit le tag npm `latest` — pas ce que le client Expo Go publié supporte
réellement) au SDK 54, pour matcher la version installée sur le téléphone de
test (Expo Go "client version 54.0.8"). Ne pas remonter le SDK sans vérifier
d'abord la version supportée par Expo Go (onglet Profil de l'app).
