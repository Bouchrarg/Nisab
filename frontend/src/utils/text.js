// Le texte des articles conserve un \n à chaque ligne du PDF d'origine (pas
// seulement entre paragraphes) : affiché tel quel avec white-space: pre-wrap,
// ça bride le texte à la largeur d'une ligne de PDF au lieu de remplir le
// conteneur. On ne touche qu'aux sauts de ligne isolés (ni précédés ni
// suivis d'un autre \n) : les vrais sauts de paragraphe (\n\n) sont préservés.
export function reflowText(text) {
  if (!text) return text
  return text.replace(/(?<!\n)\n(?!\n)/g, ' ')
}
