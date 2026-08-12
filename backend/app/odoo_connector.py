
from __future__ import annotations

import xmlrpc.client
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


#: Nombre de chiffres minimum pour qu'un code comptable puisse être résolu par
#: préfixe. Voir OdooConnector.resolve_account pour le raisonnement.
LONGUEUR_MIN_PREFIXE_COMPTE = 4


class OdooWriteError(Exception):
    """
    Échec d'une écriture dans Odoo, avec un message destiné à un comptable.

    Distincte des erreurs de lecture : ici l'utilisateur a explicitement demandé
    la création d'un brouillon, il a droit à une explication actionnable
    (« le compte 6142 n'existe pas dans ce plan comptable ») et non à une trace
    XML-RPC.
    """


@dataclass
class OdooConnector:
    url: str
    db: str
    username: str
    password: str
    uid: Optional[int] = None

    company_id: Optional[int] = None

 
    def authenticate(self) -> int:
        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        uid = common.authenticate(self.db, self.username, self.password, {})
        if not uid:
            raise ValueError(
                f"Authentification échouée pour {self.username} sur {self.url}/{self.db}. "
                "Vérifiez l'URL, la base de données, le login et le mot de passe."
            )
        self.uid = uid
        return uid

    def _models(self):
        return xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    def _execute(self, model: str, method: str, *args, **kwargs):
        """
        Wrapper générique pour exécuter une méthode Odoo.

        Injecte `allowed_company_ids` dès que company_id est connu — voir la
        note sur le contexte de société en tête de classe. `setdefault` plutôt
        qu'écrasement : un appelant qui passe déjà un contexte garde le sien.
        """
        if self.uid is None:
            raise RuntimeError("Non authentifié — appelez authenticate() d'abord.")
        if self.company_id is not None:
            kwargs.setdefault("context", {}).setdefault("allowed_company_ids", [self.company_id])
        return self._models().execute_kw(
            self.db, self.uid, self.password,
            model, method, list(args), kwargs
        )

    def detect_company_id(self) -> Optional[int]:
        """
        Société qui détient réellement la comptabilité, déduite des écritures.

        On ne prend PAS la société courante de l'utilisateur Odoo : sur une
        base multi-sociétés elle est souvent restée sur la société par défaut
        (« My Company »), qui n'a aucune écriture — cas observé sur une base
        réelle. On ne prend pas non plus la première de la liste : `res.company`
        sans ordre explicite renvoie un premier arbitraire.

        La société qui compte est celle où vivent les écritures. En cas
        d'égalité improbable, la plus fournie gagne.
        """
        cutoff = (date.today() - timedelta(days=365)).isoformat()
        echantillon = self._execute(
            "account.move", "search_read",
            [["state", "=", "posted"], ["date", ">=", cutoff]],
            fields=["company_id"], limit=200,
        )
        compte: dict[int, int] = {}
        for m in echantillon:
            if m.get("company_id"):
                compte[m["company_id"][0]] = compte.get(m["company_id"][0], 0) + 1
        if compte:
            return max(compte, key=compte.get)

        # Aucune écriture : on se rabat sur la société de l'utilisateur, faute
        # de meilleur signal.
        users = self._execute("res.users", "read", [self.uid], fields=["company_id"])
        if users and users[0].get("company_id"):
            return users[0]["company_id"][0]
        return None

    def fetch_accounting_data(self) -> dict:
        # Société cible d'abord : tout ce qui suit en dépend. Sans elle, sur une
        # base multi-sociétés, on agrégerait plusieurs comptabilités en une
        # seule et l'audit raisonnerait sur un mélange — inacceptable pour un
        # produit dont l'argument est l'isolation stricte des données.
        if self.company_id is None:
            self.company_id = self.detect_company_id()

        filtre_societe = [["company_id", "=", self.company_id]] if self.company_id else []

        # Company info
        company_fields = ["name", "vat", "country_id", "currency_id"]
        companies = self._execute(
            "res.company", "search_read",
            [["id", "=", self.company_id]] if self.company_id else [],
            fields=company_fields, limit=1,
        )
        company = companies[0] if companies else {}

        # Partners (fournisseurs avec ICE/VAT)
        # Les tiers peuvent être partagés entre sociétés (company_id = False) :
        # on garde donc les partagés ET ceux de la société cible, au lieu d'un
        # filtre strict qui les ferait disparaître.
        partner_fields = ["id", "name", "vat", "supplier_rank", "customer_rank", "street", "city"]
        partner_domain = [["active", "=", True]]
        if self.company_id:
            partner_domain += ["|", ["company_id", "=", False], ["company_id", "=", self.company_id]]
        partners = self._execute("res.partner", "search_read",
                                partner_domain,
                                fields=partner_fields, limit=200)

        # Validated journal entries (last 12 months)
        cutoff = (date.today() - timedelta(days=365)).isoformat()
        move_fields = ["id", "name", "date", "journal_id", "partner_id", "move_type",
                    "amount_total", "payment_state", "ref", "state"]
        moves = self._execute("account.move", "search_read",
                            [["state", "=", "posted"],
                            ["date", ">=", cutoff]] + filtre_societe,
                            fields=move_fields, limit=500, order="date desc")

        # Type de chaque journal, reporté sur les écritures.
        #
        # Pourquoi c'est nécessaire : le mode de règlement n'existe NULLE PART
        # dans `account.move.line` — `payment_mode` n'est pas un champ Odoo
        # standard, il n'apparaît que dans les scénarios de démonstration plus
        # bas dans ce fichier. Or l'Art. 11-II du CGI plafonne la déductibilité
        # d'une charge selon qu'elle a été réglée ou non par un moyen traçable
        # (voir regles_montant.py) : sans un signal sur le caractère espèces du
        # règlement, cette règle ne pourrait se déclencher qu'en démo, jamais
        # sur une base réelle. Le type du journal (`cash`) est le signal
        # structurel le plus proche qu'Odoo expose nativement.
        #
        # `detection_reglee.est_regle_en_especes()` s'en sert comme second
        # signal, avec un repli sur la contrepartie en compte de caisse (516x
        # au plan CGNC) — les deux sont nécessaires parce qu'une facture
        # d'achat reste enregistrée dans un journal d'achats même lorsqu'elle
        # est payée en espèces ; c'est l'écriture de règlement qui porte le
        # journal de caisse.
        journaux = self._execute("account.journal", "search_read",
                                filtre_societe,
                                fields=["id", "type", "code", "name"], limit=200)
        type_par_journal = {j["id"]: j.get("type") for j in journaux}
        for m in moves:
            journal = m.get("journal_id")
            if isinstance(journal, list) and journal:
                m["journal_type"] = type_par_journal.get(journal[0])

        # Journal entry lines
        line_fields = ["move_id", "account_id", "name", "debit", "credit",
                    "tax_ids", "tax_line_id", "partner_id", "date",
                    "amount_currency"]
        move_ids = [m["id"] for m in moves]
        lines = []
        if move_ids:
            lines = self._execute("account.move.line", "search_read",
                                [["move_id", "in", move_ids]],
                                fields=line_fields, limit=5000)

        return {
            "company": company,
            "partners": partners,
            "moves": moves,
            "lines": lines,
            "source": "odoo_live",
            # Mémorisé dans le snapshot : le workflow de correction doit pouvoir
            # écrire dans LA MÊME société que celle qui a été auditée, sans avoir
            # à la redeviner (et donc sans risquer de la deviner autrement).
            "company_id": self.company_id,
        }

    # ── Écriture (workflow de correction) ────────────────────────────────

    def resolve_journal(self, code: str | None = None) -> int:
        """Journal cible : par code si fourni, sinon le premier journal d'OD."""
        if code:
            res = self._execute("account.journal", "search_read",
                                [["code", "=", code]], fields=["id"], limit=1)
            if res:
                return res[0]["id"]
        res = self._execute("account.journal", "search_read",
                            [["type", "=", "general"]], fields=["id", "code"], limit=1, order="id")
        if not res:
            raise OdooWriteError(
                "Aucun journal d'opérations diverses dans cette société Odoo. "
                "Créez-en un (Comptabilité > Configuration > Journaux) avant de pousser une correction."
            )
        return res[0]["id"]

    def resolve_account(self, code: str) -> dict:
        """
        Trouve un compte à partir d'un code du plan marocain.

        Le décalage à absorber : le CGI, les manuels et donc le LLM raisonnent
        en codes CGNC à 4 chiffres (6142, 4411), alors que le plan livré par
        Odoo les complète à 6 (614210, 441110). Une recherche par égalité ne
        trouverait donc jamais rien.

        Stratégie, dans cet ordre :
          1. égalité exacte — si le LLM a donné le code complet, on le prend ;
          2. préfixe, en retenant le code le plus court puis le plus petit.
             Déterministe et reproductible : deux exécutions sur la même base
             choisissent le même compte, ce qui est indispensable puisqu'un
             humain valide la proposition avant qu'elle ne parte.

        Ne crée JAMAIS de compte et n'en devine jamais un hors du préfixe
        demandé : inventer un compte de charge revient à falsifier une écriture.
        """
        code = str(code).strip()
        if not code:
            raise OdooWriteError("Code comptable vide dans la proposition.")

        exact = self._execute("account.account", "search_read",
                              [["code", "=", code]], fields=["id", "code", "name"], limit=1)
        if exact:
            return {**exact[0], "resolution": "exacte"}

        # Longueur minimale avant d'accepter une résolution par préfixe. Dans le
        # plan marocain, 4 chiffres identifient le compte principal (6142 =
        # transports) ; en dessous on ne désigne qu'une rubrique entière, et
        # "6" résoudrait vers le premier compte de charge venu. Un code trop
        # court est le symptôme d'une hallucination, pas d'une abréviation :
        # on refuse au lieu de deviner.
        if len(code) < LONGUEUR_MIN_PREFIXE_COMPTE:
            raise OdooWriteError(
                f"Code comptable « {code} » trop imprécis pour être résolu sans ambiguïté "
                f"({LONGUEUR_MIN_PREFIXE_COMPTE} chiffres minimum attendus). "
                "Corrigez le compte dans la proposition avant de la pousser."
            )

        candidats = self._execute("account.account", "search_read",
                                  [["code", "=like", f"{code}%"]],
                                  fields=["id", "code", "name"], limit=20)
        if not candidats:
            raise OdooWriteError(
                f"Aucun compte commençant par {code} dans le plan comptable de cette société Odoo. "
                "Vérifiez le plan comptable, ou corrigez le compte dans la proposition avant de la pousser."
            )
        choisi = sorted(candidats, key=lambda c: (len(str(c["code"])), str(c["code"])))[0]
        return {
            **choisi,
            "resolution": "prefixe",
            # Remonté à l'interface : l'utilisateur doit voir que 6142 a été
            # résolu en 614210 « Transport of Personnel », et pas le découvrir
            # dans Odoo après coup.
            "candidats": [{"code": c["code"], "name": c["name"]} for c in candidats[:8]],
        }

    def create_draft_move(
        self,
        lignes: list[dict],
        date_ecriture: str,
        ref: str,
        narration: str = "",
        journal_code: str | None = None,
    ) -> dict:
        """
        Crée une écriture comptable **en brouillon** dans Odoo.

        RÈGLE PRODUIT NON NÉGOCIABLE : cette méthode n'appelle JAMAIS
        `action_post`. Nisab ne valide aucune écriture comptable, jamais. Elle
        dépose une proposition déjà relue et validée par un humain dans Nisab,
        que le comptable relit une seconde fois dans son ERP et poste lui-même
        s'il est d'accord. Le dernier geste comptable reste au comptable —
        c'est une règle d'architecture du projet et le fondement de la
        responsabilité professionnelle en cas de contrôle.

        `lignes` : [{"compte": "6142", "libelle": "...", "debit": 0.0, "credit": 0.0}]
        L'équilibre débit/crédit a déjà été vérifié en amont (correction_agent),
        mais on ne fait pas confiance à l'amont : Odoo refusera de toute façon
        une écriture déséquilibrée, et mieux vaut son refus qu'un brouillon faux.
        """
        if self.company_id is None:
            self.company_id = self.detect_company_id()

        journal_id = self.resolve_journal(journal_code)

        line_ids = []
        comptes_resolus = []
        for ligne in lignes:
            compte = self.resolve_account(ligne.get("compte", ""))
            comptes_resolus.append({"demande": ligne.get("compte"), **compte})
            line_ids.append((0, 0, {
                "account_id": compte["id"],
                "name": (ligne.get("libelle") or ref)[:200],
                "debit": round(float(ligne.get("debit") or 0), 2),
                "credit": round(float(ligne.get("credit") or 0), 2),
            }))

        valeurs = {
            "move_type": "entry",
            "journal_id": journal_id,
            "date": date_ecriture,
            "ref": ref[:200],
            "narration": narration,
            "line_ids": line_ids,
        }
        if self.company_id:
            valeurs["company_id"] = self.company_id

        try:
            move_id = self._execute("account.move", "create", [valeurs])
        except Exception as exc:
            raise OdooWriteError(f"Odoo a refusé l'écriture : {_derniere_ligne(exc)}") from exc

        if isinstance(move_id, list):
            move_id = move_id[0]

        # On vérifie que le brouillon est bien un brouillon plutôt que de le
        # supposer : si une automatisation Odoo l'a posté (règle serveur,
        # module tiers), il faut le dire, pas laisser croire que la règle
        # « jamais d'écriture automatique » a été respectée.
        etat = self._execute("account.move", "read", [move_id], fields=["state", "name"])
        state = etat[0]["state"] if etat else "?"
        if state != "draft":
            raise OdooWriteError(
                f"L'écriture a été créée mais son état est « {state} » au lieu de « draft ». "
                "Une automatisation Odoo l'a validée : vérifiez-la immédiatement dans l'ERP."
            )

        return {
            "move_id": move_id,
            "name": etat[0].get("name") if etat else None,
            "state": state,
            "url": self.move_url(move_id),
            "journal_id": journal_id,
            "company_id": self.company_id,
            "comptes_resolus": comptes_resolus,
        }

    def move_url(self, move_id: int) -> str:
        """
        Lien profond vers l'écriture dans l'interface Odoo.

        Forme `/web#id=...` : elle fonctionne de la v13 à la v18, alors que la
        nouvelle route `/odoo/...` d'Odoo 17+ n'existe pas sur les versions
        antérieures. Un lien qui marche partout vaut mieux qu'un lien moderne
        qui casse chez un client resté sur une v16.
        """
        return f"{self.url.rstrip('/')}/web#id={move_id}&model=account.move&view_type=form"


def _derniere_ligne(exc: Exception) -> str:
    """Les Fault XML-RPC portent toute la trace serveur ; seule la fin est utile."""
    lignes = [l.strip() for l in str(exc).replace("\\n", "\n").splitlines() if l.strip()]
    return lignes[-1] if lignes else str(exc)


# ─────────────────────────────────────────────────────────────────────────────
# DONNÉES DE DÉMONSTRATION (PME fictives, pour tester sans instance Odoo réelle)
# ─────────────────────────────────────────────────────────────────────────────
#
# Trois scénarios, choisis pour couvrir des chemins différents de l'audit :
# - "commerce"  : PME avec anomalies variées (scénario historique, inchangé).
# - "conforme"  : aucune anomalie — seul moyen de voir l'état "audit propre"
#                 (Conforme, 0 alerte) sans données Odoo réelles déjà nettoyées.
# - "services"  : anomalies différentes du scénario commerce (retenue à la
#                 source, facturation irrégulière) plutôt que cotisation
#                 minimale — l'audit RAG tourne par écriture individuelle
#                 (voir ai_auditor.run_ai_rag_audit), pas de façon agrégée sur
#                 l'année, donc un seuil annuel comme la cotisation minimale
#                 n'est pas déclenchable de façon réaliste par une seule
#                 écriture synthétique.


def _demo_commerce() -> dict:
    company = {
        "id": 1,
        "name": "Atlas Négoce SARL",
        "vat": "MA002345678901",
        "country_id": [110, "Maroc"],
        "currency_id": [147, "MAD"],
    }

    partners = [
        {"id": 10, "name": "Fournisseur Al Baraka", "vat": None,
         "supplier_rank": 1, "customer_rank": 0, "city": "Casablanca"},
        {"id": 11, "name": "Fournisseur TechMaroc SARL", "vat": "MA001234567890",
         "supplier_rank": 1, "customer_rank": 0, "city": "Rabat"},
        {"id": 12, "name": "Fournisseur Equipements Pro", "vat": None,
         "supplier_rank": 1, "customer_rank": 0, "city": "Fès"},
        {"id": 13, "name": "Client Marjane Holding", "vat": "MA009876543210",
         "supplier_rank": 0, "customer_rank": 1, "city": "Casablanca"},
        {"id": 14, "name": "Client Al Mazar SAS", "vat": None,
         "supplier_rank": 0, "customer_rank": 1, "city": "Marrakech"},
        {"id": 15, "name": "Fournisseur Carburants Sud", "vat": None,
         "supplier_rank": 1, "customer_rank": 0, "city": "Agadir"},
    ]

    moves = [
        # Facture normale
        {"id": 101, "name": "FACT-2026-001", "date": "2026-01-15",
         "journal_id": [1, "Achats"], "partner_id": [11, "Fournisseur TechMaroc SARL"],
         "move_type": "in_invoice", "amount_total": 24000.0,
         "payment_state": "paid", "ref": "INV-2026-001", "state": "posted"},
        # Achat en espèces >= 20 000 DH (Anomalie -> Art. 193 : seuil vérifié
        # dans le corpus CGI 2025-2026, "vingt mille (20.000) dirhams" — PAS
        # 5 000 DH comme un ancien commentaire ici le prétendait ; voir
        # app/regles_montant.py, SEUIL_ESPECES_ART193).
        {"id": 102, "name": "FACT-2026-002", "date": "2026-01-20",
         "journal_id": [2, "Caisse"], "partner_id": [10, "Fournisseur Al Baraka"],
         "move_type": "in_invoice", "amount_total": 24000.0,
         "payment_state": "paid", "ref": None, "state": "posted"},
        # Fournisseur sans ICE (Anomalie → ICE obligatoire depuis 2017)
        {"id": 103, "name": "FACT-2026-003", "date": "2026-02-05",
         "journal_id": [1, "Achats"], "partner_id": [12, "Fournisseur Equipements Pro"],
         "move_type": "in_invoice", "amount_total": 45000.0,
         "payment_state": "paid", "ref": "EQ-2026-03", "state": "posted"},
        # Amortissement véhicule de tourisme > 400 000 DH TTC (Anomalie ->
        # Art. 10-I-F-1°-b : plafond vérifié dans le corpus, "quatre cent
        # mille (400 000) dirhams par véhicule, TVA comprise" — PAS
        # 300 000 DH comme un ancien commentaire ici le prétendait ; voir
        # app/regles_montant.py, PLAFOND_VEHICULE_TOURISME_TTC).
        {"id": 104, "name": "IMMO-2026-001", "date": "2026-01-01",
         "journal_id": [5, "OD Amortissements"], "partner_id": False,
         "move_type": "entry", "amount_total": 85000.0,
         "payment_state": False, "ref": "Amort. Véhicule Tourisme 450000DH",
         "state": "posted"},
        # Facture client normale
        {"id": 105, "name": "VENTE-2026-001", "date": "2026-02-10",
         "journal_id": [3, "Ventes"], "partner_id": [13, "Client Marjane Holding"],
         "move_type": "out_invoice", "amount_total": 120000.0,
         "payment_state": "paid", "ref": None, "state": "posted"},
        # Deuxième achat en espèces, même fournisseur, montant unitaire déjà
        # >= 20 000 DH à lui seul. (Le texte vérifié de l'Art. 193 ne prévoit
        # AUCUN cumul mensuel par fournisseur — un ancien commentaire ici
        # l'affirmait à tort ; le seuil s'apprécie transaction par
        # transaction, voir regles_montant.paiement_especes_art193.)
        {"id": 106, "name": "FACT-2026-004", "date": "2026-01-28",
         "journal_id": [2, "Caisse"], "partner_id": [10, "Fournisseur Al Baraka"],
         "move_type": "in_invoice", "amount_total": 47000.0,
         "payment_state": "paid", "ref": None, "state": "posted"},
        # Note de restaurant d'affaires. Signalée par le RAG au titre d'un
        # article candidat, mais l'Art. 106-I (TVA, catégories exclues du
        # droit à déduction) vérifié dans le corpus liste explicitement 4
        # catégories — véhicules de tourisme, immeubles non liés à
        # l'exploitation, produits pétroliers hors liste, biens non utilisés
        # pour l'exploitation — et les frais de réception/restaurant n'en
        # font PAS partie. `regles_montant.categorie_art106()` ne reconnaît
        # donc pas ce libellé : la règle 3 répond `non_calculable`, pas un 0
        # silencieux ni un montant inventé. Volontairement laissé ainsi,
        # comme démonstration du garde-fou plutôt que "corrigé" vers un
        # rattachement qui ne serait pas mieux fondé.
        {"id": 107, "name": "FACT-2026-005", "date": "2026-03-12",
         "journal_id": [1, "Achats"], "partner_id": [15, "Fournisseur Carburants Sud"],
         "move_type": "in_invoice", "amount_total": 3200.0,
         "payment_state": "paid", "ref": "Repas d'affaires clients mars 2026",
         "state": "posted"},
    ]

    lines = [
        # Lines pour FACT-2026-002 (espèces, 20 000 DH HT + 4 000 DH TVA 20%)
        {"id": 201, "move_id": [102, "FACT-2026-002"], "account_id": [612, "Achats"],
         "name": "Marchandises", "debit": 20000.0, "credit": 0.0,
         "tax_ids": [10], "tax_line_id": False, "partner_id": [10, "Fournisseur Al Baraka"],
         "date": "2026-01-20", "payment_mode": "cash", "amount_currency": 0.0},
        {"id": 202, "move_id": [102, "FACT-2026-002"], "account_id": [34552, "TVA déductible"],
         "name": "TVA 20%", "debit": 4000.0, "credit": 0.0,
         "tax_ids": [], "tax_line_id": 10, "partner_id": [10, "Fournisseur Al Baraka"],
         "date": "2026-01-20", "payment_mode": "cash", "amount_currency": 0.0},
        # Lines pour FACT-2026-004 (espèces, 39 166,67 DH HT + 7 833,33 DH
        # TVA 20% = 47 000 DH). Ce move n'avait AUCUNE ligne avant le
        # branchement du moteur de règles — un trou resté invisible tant que
        # amount_risk était inventé par le LLM sans jamais vérifier
        # payment_mode. paiement_especes_art193() lit les lignes, pas
        # move.amount_total seul : sans elles, l'anomalie ne se déclenchait
        # plus du tout.
        {"id": 206, "move_id": [106, "FACT-2026-004"], "account_id": [612, "Achats"],
         "name": "Marchandises", "debit": 39166.67, "credit": 0.0,
         "tax_ids": [10], "tax_line_id": False, "partner_id": [10, "Fournisseur Al Baraka"],
         "date": "2026-01-28", "payment_mode": "cash", "amount_currency": 0.0},
        {"id": 207, "move_id": [106, "FACT-2026-004"], "account_id": [34552, "TVA déductible"],
         "name": "TVA 20%", "debit": 7833.33, "credit": 0.0,
         "tax_ids": [], "tax_line_id": 10, "partner_id": [10, "Fournisseur Al Baraka"],
         "date": "2026-01-28", "payment_mode": "cash", "amount_currency": 0.0},
        # Lines pour IMMO (amortissement voiture)
        {"id": 203, "move_id": [104, "IMMO-2026-001"],
         "account_id": [61930, "Dotations amortissements"],
         "name": "Amort. véhicule tourisme 450000 DH (taux 20%)",
         "debit": 90000.0, "credit": 0.0,
         "tax_ids": [], "tax_line_id": False, "partner_id": False,
         "date": "2026-01-01", "payment_mode": False, "amount_currency": 0.0},
        # Lines pour resto
        {"id": 204, "move_id": [107, "FACT-2026-005"],
         "account_id": [6185, "Charges de réception"], "name": "Repas d'affaires clients",
         "debit": 2666.67, "credit": 0.0,
         "tax_ids": [10], "tax_line_id": False, "partner_id": [15, "Fournisseur Carburants Sud"],
         "date": "2026-03-12", "payment_mode": "bank", "amount_currency": 0.0},
        {"id": 205, "move_id": [107, "FACT-2026-005"], "account_id": [34552, "TVA déductible"],
         "name": "TVA 20% Repas d'affaires", "debit": 533.33, "credit": 0.0,
         "tax_ids": [], "tax_line_id": 10, "partner_id": [15, "Fournisseur Carburants Sud"],
         "date": "2026-03-12", "payment_mode": "bank", "amount_currency": 0.0},
        # Lines pour VENTE-2026-001 (120 000 DH TTC = 100 000 DH HT +
        # 20 000 DH TVA 20%) — ce move n'avait AUCUNE ligne avant le
        # branchement du ROI échéances (tax_calendar._montant_tva_periode) :
        # une vente sans ligne "TVA facturée" est aussi irréaliste qu'un
        # achat sans "TVA déductible" (déjà corrigé plus haut, cf. le
        # commentaire sur FACT-2026-004), et sans elle, la TVA due ne pouvait
        # jamais se calculer — seule la TVA déductible existait dans ce
        # corpus de démo, jamais la TVA collectée sur les ventes.
        {"id": 208, "move_id": [105, "VENTE-2026-001"], "account_id": [711100, "Ventes de marchandises"],
         "name": "Vente de marchandises", "debit": 0.0, "credit": 100000.0,
         "tax_ids": [10], "tax_line_id": False, "partner_id": [13, "Client Marjane Holding"],
         "date": "2026-02-10", "payment_mode": "virement", "amount_currency": 0.0},
        {"id": 209, "move_id": [105, "VENTE-2026-001"], "account_id": [44551, "TVA facturée"],
         "name": "TVA 20%", "debit": 0.0, "credit": 20000.0,
         "tax_ids": [], "tax_line_id": 10, "partner_id": [13, "Client Marjane Holding"],
         "date": "2026-02-10", "payment_mode": "virement", "amount_currency": 0.0},
    ]

    return {
        "company": company,
        "partners": partners,
        "moves": moves,
        "lines": lines,
        "source": "demo",
    }


def _demo_conforme() -> dict:
    company = {
        "id": 1,
        "name": "Rif Distribution SARL",
        "vat": "MA003456789012",
        "country_id": [110, "Maroc"],
        "currency_id": [147, "MAD"],
    }

    # Tous les fournisseurs/clients ont leur ICE (vat) renseigné — condition
    # de base pour ne déclencher aucune anomalie de facturation (Article 146).
    partners = [
        {"id": 20, "name": "Fournisseur Atlas Papeterie SARL", "vat": "MA005678901234",
         "supplier_rank": 1, "customer_rank": 0, "city": "Casablanca"},
        {"id": 21, "name": "Fournisseur Maroc Informatique SA", "vat": "MA006789012345",
         "supplier_rank": 1, "customer_rank": 0, "city": "Rabat"},
        {"id": 22, "name": "Client Label'Vie SA", "vat": "MA007890123456",
         "supplier_rank": 0, "customer_rank": 1, "city": "Casablanca"},
        {"id": 23, "name": "Client Bim Maroc", "vat": "MA008901234567",
         "supplier_rank": 0, "customer_rank": 1, "city": "Tanger"},
    ]

    moves = [
        {"id": 301, "name": "FACT-2026-101", "date": "2026-01-10",
         "journal_id": [1, "Achats"], "partner_id": [20, "Fournisseur Atlas Papeterie SARL"],
         "move_type": "in_invoice", "amount_total": 12000.0,
         "payment_state": "paid", "ref": "APAP-2026-014", "state": "posted"},
        {"id": 302, "name": "FACT-2026-102", "date": "2026-01-25",
         "journal_id": [1, "Achats"], "partner_id": [21, "Fournisseur Maroc Informatique SA"],
         "move_type": "in_invoice", "amount_total": 32000.0,
         "payment_state": "paid", "ref": "MI-2026-089", "state": "posted"},
        {"id": 303, "name": "VENTE-2026-101", "date": "2026-02-03",
         "journal_id": [3, "Ventes"], "partner_id": [22, "Client Label'Vie SA"],
         "move_type": "out_invoice", "amount_total": 85000.0,
         "payment_state": "paid", "ref": None, "state": "posted"},
        {"id": 304, "name": "VENTE-2026-102", "date": "2026-02-18",
         "journal_id": [3, "Ventes"], "partner_id": [23, "Client Bim Maroc"],
         "move_type": "out_invoice", "amount_total": 54000.0,
         "payment_state": "paid", "ref": None, "state": "posted"},
    ]

    lines = [
        {"id": 401, "move_id": [301, "FACT-2026-101"], "account_id": [612, "Achats"],
         "name": "Fournitures de bureau", "debit": 10000.0, "credit": 0.0,
         "tax_ids": [10], "tax_line_id": False, "partner_id": [20, "Fournisseur Atlas Papeterie SARL"],
         "date": "2026-01-10", "payment_mode": "virement", "amount_currency": 0.0},
        {"id": 402, "move_id": [301, "FACT-2026-101"], "account_id": [34552, "TVA déductible"],
         "name": "TVA 20%", "debit": 2000.0, "credit": 0.0,
         "tax_ids": [], "tax_line_id": 10, "partner_id": [20, "Fournisseur Atlas Papeterie SARL"],
         "date": "2026-01-10", "payment_mode": "virement", "amount_currency": 0.0},
        {"id": 403, "move_id": [302, "FACT-2026-102"], "account_id": [612, "Achats"],
         "name": "Matériel informatique", "debit": 26666.67, "credit": 0.0,
         "tax_ids": [10], "tax_line_id": False, "partner_id": [21, "Fournisseur Maroc Informatique SA"],
         "date": "2026-01-25", "payment_mode": "cheque", "amount_currency": 0.0},
        {"id": 404, "move_id": [302, "FACT-2026-102"], "account_id": [34552, "TVA déductible"],
         "name": "TVA 20%", "debit": 5333.33, "credit": 0.0,
         "tax_ids": [], "tax_line_id": 10, "partner_id": [21, "Fournisseur Maroc Informatique SA"],
         "date": "2026-01-25", "payment_mode": "cheque", "amount_currency": 0.0},
        # Lines pour VENTE-2026-101 (85 000 DH TTC = 70 833,33 DH HT +
        # 14 166,67 DH TVA 20%) et VENTE-2026-102 (54 000 DH TTC =
        # 45 000 DH HT + 9 000 DH TVA 20%) — même trou que dans
        # _demo_commerce (voir son commentaire) : aucune vente n'avait de
        # ligne "TVA facturée" dans ce corpus de démo.
        {"id": 405, "move_id": [303, "VENTE-2026-101"], "account_id": [711100, "Ventes de marchandises"],
         "name": "Vente de marchandises", "debit": 0.0, "credit": 70833.33,
         "tax_ids": [10], "tax_line_id": False, "partner_id": [22, "Client Label'Vie SA"],
         "date": "2026-02-03", "payment_mode": "virement", "amount_currency": 0.0},
        {"id": 406, "move_id": [303, "VENTE-2026-101"], "account_id": [44551, "TVA facturée"],
         "name": "TVA 20%", "debit": 0.0, "credit": 14166.67,
         "tax_ids": [], "tax_line_id": 10, "partner_id": [22, "Client Label'Vie SA"],
         "date": "2026-02-03", "payment_mode": "virement", "amount_currency": 0.0},
        {"id": 407, "move_id": [304, "VENTE-2026-102"], "account_id": [711100, "Ventes de marchandises"],
         "name": "Vente de marchandises", "debit": 0.0, "credit": 45000.0,
         "tax_ids": [10], "tax_line_id": False, "partner_id": [23, "Client Bim Maroc"],
         "date": "2026-02-18", "payment_mode": "virement", "amount_currency": 0.0},
        {"id": 408, "move_id": [304, "VENTE-2026-102"], "account_id": [44551, "TVA facturée"],
         "name": "TVA 20%", "debit": 0.0, "credit": 9000.0,
         "tax_ids": [], "tax_line_id": 10, "partner_id": [23, "Client Bim Maroc"],
         "date": "2026-02-18", "payment_mode": "virement", "amount_currency": 0.0},
    ]

    return {
        "company": company,
        "partners": partners,
        "moves": moves,
        "lines": lines,
        "source": "demo",
    }


def _demo_services() -> dict:
    company = {
        "id": 1,
        "name": "Maroc Digital Services SARL",
        "vat": "MA009012345678",
        "country_id": [110, "Maroc"],
        "currency_id": [147, "MAD"],
    }

    partners = [
        # Consultant indépendant sans ICE ni numéro d'identification fiscale
        # renseigné — cible Article 151 (déclaration des rémunérations
        # allouées à des tiers) sur l'écriture d'honoraires ci-dessous.
        {"id": 30, "name": "Consultant Indépendant K. Amrani", "vat": None,
         "supplier_rank": 1, "customer_rank": 0, "city": "Casablanca"},
        {"id": 31, "name": "Fournisseur Bureau Design SARL", "vat": None,
         "supplier_rank": 1, "customer_rank": 0, "city": "Rabat"},
        {"id": 32, "name": "Client StartUp Maroc SAS", "vat": "MA010123456789",
         "supplier_rank": 0, "customer_rank": 1, "city": "Casablanca"},
        # Deuxième cas de rémunération à un tiers non déclaré — même thème
        # que le consultant (Art. 151), pour fiabiliser sa détection (un
        # jugement LLM isolé peut varier d'une exécution à l'autre).
        {"id": 33, "name": "Apporteur d'affaires H. Bennani", "vat": None,
         "supplier_rank": 1, "customer_rank": 0, "city": "Marrakech"},
        {"id": 34, "name": "Service Nettoyage Pro", "vat": None,
         "supplier_rank": 1, "customer_rank": 0, "city": "Casablanca"},
    ]

    moves = [
        # Honoraires versés à un consultant sans déclaration à la taxe
        # professionnelle / ICE (Anomalie -> Art. 151)
        {"id": 501, "name": "FACT-2026-201", "date": "2026-02-08",
         "journal_id": [1, "Achats"], "partner_id": [30, "Consultant Indépendant K. Amrani"],
         "move_type": "in_invoice", "amount_total": 38000.0,
         "payment_state": "paid", "ref": "Honoraires conseil strategique fevrier 2026",
         "state": "posted"},
        # Facture sans référence, sans ICE fournisseur (Anomalie -> Art. 146,
        # mentions obligatoires manquantes)
        {"id": 502, "name": "FACT-2026-202", "date": "2026-02-22",
         "journal_id": [1, "Achats"], "partner_id": [31, "Fournisseur Bureau Design SARL"],
         "move_type": "in_invoice", "amount_total": 15500.0,
         "payment_state": "paid", "ref": None, "state": "posted"},
        # Facture client normale, pour contraste
        {"id": 503, "name": "VENTE-2026-201", "date": "2026-03-01",
         "journal_id": [3, "Ventes"], "partner_id": [32, "Client StartUp Maroc SAS"],
         "move_type": "out_invoice", "amount_total": 96000.0,
         "payment_state": "paid", "ref": None, "state": "posted"},
        # Commission versée à un apporteur d'affaires non déclaré, sans ICE
        # (Anomalie -> Art. 151, deuxième occurrence du même thème)
        {"id": 504, "name": "FACT-2026-203", "date": "2026-03-05",
         "journal_id": [1, "Achats"], "partner_id": [33, "Apporteur d'affaires H. Bennani"],
         "move_type": "in_invoice", "amount_total": 22000.0,
         "payment_state": "paid", "ref": "Commission apport affaires mars 2026",
         "state": "posted"},
        # Paiement en espèces >= 20 000 DH pour une prestation de nettoyage
        # (Anomalie -> Art. 193, thème distinct des deux précédents ; seuil
        # vérifié dans le corpus, voir le commentaire équivalent dans
        # _demo_commerce)
        {"id": 505, "name": "FACT-2026-204", "date": "2026-03-15",
         "journal_id": [2, "Caisse"], "partner_id": [34, "Service Nettoyage Pro"],
         "move_type": "in_invoice", "amount_total": 22200.0,
         "payment_state": "paid", "ref": None, "state": "posted"},
    ]

    lines = [
        {"id": 601, "move_id": [501, "FACT-2026-201"], "account_id": [6135, "Honoraires"],
         "name": "Honoraires conseil stratégique", "debit": 38000.0, "credit": 0.0,
         "tax_ids": [], "tax_line_id": False, "partner_id": [30, "Consultant Indépendant K. Amrani"],
         "date": "2026-02-08", "payment_mode": "virement", "amount_currency": 0.0},
        {"id": 602, "move_id": [502, "FACT-2026-202"], "account_id": [612, "Achats"],
         "name": "Amenagement bureaux", "debit": 12916.67, "credit": 0.0,
         "tax_ids": [10], "tax_line_id": False, "partner_id": [31, "Fournisseur Bureau Design SARL"],
         "date": "2026-02-22", "payment_mode": "virement", "amount_currency": 0.0},
        {"id": 603, "move_id": [502, "FACT-2026-202"], "account_id": [34552, "TVA déductible"],
         "name": "TVA 20%", "debit": 2583.33, "credit": 0.0,
         "tax_ids": [], "tax_line_id": 10, "partner_id": [31, "Fournisseur Bureau Design SARL"],
         "date": "2026-02-22", "payment_mode": "virement", "amount_currency": 0.0},
        {"id": 604, "move_id": [504, "FACT-2026-203"], "account_id": [6135, "Honoraires"],
         "name": "Commission apport affaires", "debit": 22000.0, "credit": 0.0,
         "tax_ids": [], "tax_line_id": False, "partner_id": [33, "Apporteur d'affaires H. Bennani"],
         "date": "2026-03-05", "payment_mode": "virement", "amount_currency": 0.0},
        {"id": 605, "move_id": [505, "FACT-2026-204"], "account_id": [612, "Achats"],
         "name": "Prestation nettoyage bureaux mars 2026", "debit": 18500.0, "credit": 0.0,
         "tax_ids": [10], "tax_line_id": False, "partner_id": [34, "Service Nettoyage Pro"],
         "date": "2026-03-15", "payment_mode": "cash", "amount_currency": 0.0},
        {"id": 606, "move_id": [505, "FACT-2026-204"], "account_id": [34552, "TVA déductible"],
         "name": "TVA 20%", "debit": 3700.0, "credit": 0.0,
         "tax_ids": [], "tax_line_id": 10, "partner_id": [34, "Service Nettoyage Pro"],
         "date": "2026-03-15", "payment_mode": "cash", "amount_currency": 0.0},
        # Lines pour VENTE-2026-201 (96 000 DH TTC = 80 000 DH HT +
        # 16 000 DH TVA 20%) — même trou que dans _demo_commerce (voir son
        # commentaire). Compte 706 (Prestations de services) plutôt que 711
        # (Ventes de marchandises, utilisé dans _demo_commerce/_demo_conforme) :
        # cette société vend du conseil, pas de la marchandise.
        {"id": 607, "move_id": [503, "VENTE-2026-201"], "account_id": [706100, "Prestations de services"],
         "name": "Prestation de services", "debit": 0.0, "credit": 80000.0,
         "tax_ids": [10], "tax_line_id": False, "partner_id": [32, "Client StartUp Maroc SAS"],
         "date": "2026-03-01", "payment_mode": "virement", "amount_currency": 0.0},
        {"id": 608, "move_id": [503, "VENTE-2026-201"], "account_id": [44551, "TVA facturée"],
         "name": "TVA 20%", "debit": 0.0, "credit": 16000.0,
         "tax_ids": [], "tax_line_id": 10, "partner_id": [32, "Client StartUp Maroc SAS"],
         "date": "2026-03-01", "payment_mode": "virement", "amount_currency": 0.0},
    ]

    return {
        "company": company,
        "partners": partners,
        "moves": moves,
        "lines": lines,
        "source": "demo",
    }


DEMO_SCENARIOS = {
    "commerce": _demo_commerce,
    "conforme": _demo_conforme,
    "services": _demo_services,
}


def get_demo_data(scenario: str = "commerce") -> dict:
    """
    Simule les données comptables d'une PME marocaine, pour illustrer le
    moteur d'audit sans instance Odoo réelle. `scenario` inconnu retombe sur
    "commerce" (pas de régression pour un appel existant sans paramètre).
    """
    builder = DEMO_SCENARIOS.get(scenario, _demo_commerce)
    return builder()


if __name__ == "__main__":
    connector = OdooConnector(
        url="http://localhost:8069",
        db="Nisab_demo",
        username="rguibi.bouchra@ensam-casa.ma",
        password="odoo123",
    )
    connector.authenticate()

    # --- Diagnostic : lister les champs disponibles ---
    fields_info = connector._execute(
        "account.move.line", "fields_get", [], attributes=["string", "type"]
    )
    print(list(fields_info.keys()))