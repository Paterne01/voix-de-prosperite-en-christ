import sqlite3, random
from datetime import datetime, timedelta

ANGLES_SEED = [
  # Format : (pillar, angle_type, template, emotion, example)
  # PROVISION ACTIVE
  ("Provision Active", "contre-intuitif",
   "La prière ne remplacera jamais {competence}.",
   "surprise", "la discipline financière"),
  ("Provision Active", "chiffre",
   "Si tu gagnes {montant} et dépenses {montant_moins}, ton problème n'est pas ton salaire.",
   "confrontation", "100 000 FCFA / 95 000 FCFA"),
  ("Provision Active", "histoire",
   "Il avait demandé à Dieu {chose}. Mais quand il l'a obtenu, il a fait cette erreur.",
   "curiosite", "un emploi"),
  ("Provision Active", "confrontation",
   "Être pauvre n'est pas un péché. Mais {glorifier_pauvrete} peut devenir un piège.",
   "colere", "glorifier sa pauvreté"),
  ("Provision Active", "revelation",
   "Personne ne t'enseigne {sujet} dans ton église. Et c'est peut-être pour ça que tu stagnes.",
   "curiosite", "la gestion de l'argent"),
  # SAGESSE
  ("Sagesse", "contre-intuitif",
   "La décision que tu retardes depuis {duree} te coûte plus cher que tu ne le crois.",
   "peur", "6 mois"),
  ("Sagesse", "chiffre",
   "{pourcentage}% des Africains qui réussissent ont fait ceci à {age} ans.",
   "surprise", "73% / 25"),
  ("Sagesse", "confrontation",
   "Tu lis les mêmes {livres} que tout le monde, mais ta vie ne change pas. Pourquoi ?",
   "confrontation", "livres chrétiens"),
  # DIGNITE
  ("Dignité", "transformation",
   "Il y a {duree}, il dormait dans {situation}. Voici ce qui a tout changé.",
   "espoir", "2 ans / une chambre partagée"),
  ("Dignité", "revelation",
   "Dieu ne t'a pas créé pour {limitation_sociale}. Voici la preuve dans ta Bible.",
   "foi", "rester au bas de l'échelle"),
  # LIBÉRATION
  ("Libération", "confrontation",
   "Tu appelles ça de la patience. Dieu appelle ça {vrai_nom}.",
   "colere", "de la peur"),
  ("Libération", "histoire",
   "Elle avait {situation_bloquante} pendant {duree}. Une phrase a tout changé.",
   "identification", "peur d'échouer / 7 ans"),
  # PRODUCTIVITE
  ("Productivité", "chiffre",
   "{heures} heures perdues par semaine sur {activite}. Multiplie par 52. C'est ta vraie richesse perdue.",
   "peur", "8h / les réseaux sociaux"),
  ("Productivité", "contre-intuitif",
   "Travailler plus n'est pas la solution. Voici ce que {personne_reussie} fait à la place.",
   "surprise", "les entrepreneurs africains qui réussissent"),
  # RESTAURATION RELATIONNELLE
  ("Restauration relationnelle", "identification",
   "Cette relation t'a blessé. Mais {verite_difficile} est aussi vraie.",
   "identification", "ta part dans le problème"),
  ("Restauration relationnelle", "revelation",
   "Dieu peut restaurer {relation_impossible}. Mais pas si tu fais encore {erreur}.",
   "espoir", "ce mariage / cette erreur"),
  # GÉNÉROSITÉ
  ("Générosité", "contre-intuitif",
   "Donner quand tu n'as presque rien est l'un des actes les plus intelligents financièrement. Voici pourquoi.",
   "surprise", None),
  ("Générosité", "chiffre",
   "Les {pourcentage}% les plus généreux de l'Église africaine sont aussi les {resultat}.",
   "surprise", "10% / plus prospères"),
]

def init_angles(db_path: str):
    """Peuple viral_angles si vide."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM viral_angles")
    if c.fetchone()[0] == 0:
        for row in ANGLES_SEED:
            c.execute(
                "INSERT INTO viral_angles (pillar,angle_type,template,emotion,example) VALUES (?,?,?,?,?)",
                row
            )
        conn.commit()
    conn.close()

def pick_angle(db_path: str, pillar: str) -> dict:
    """
    Sélection pondérée : 70% meilleurs scores, 20% variations, 10% aléatoire.
    Évite les angles utilisés dans les 7 derniers jours.
    """
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    rows = c.execute(
        """SELECT id, angle_type, template, emotion, example, strength_score
           FROM viral_angles
           WHERE pillar=? AND (last_used IS NULL OR last_used < ?)
           ORDER BY strength_score DESC""",
        (pillar, cutoff)
    ).fetchall()
    conn.close()

    if not rows:
        # Fallback si tous récents
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        rows = c.execute(
            "SELECT id, angle_type, template, emotion, example, strength_score FROM viral_angles WHERE pillar=?",
            (pillar,)
        ).fetchall()
        conn.close()

    if not rows:
        return {"angle_type": "conseil", "template": "", "emotion": "espoir", "example": ""}

    r = random.random()
    if r < 0.70 and len(rows) >= 1:
        pool = rows[:max(1, len(rows)//2)]  # top 50%
    elif r < 0.90 and len(rows) >= 2:
        pool = rows[len(rows)//2:]           # bas 50% (exploration)
    else:
        pool = rows                           # tout (expérimentation)

    chosen = random.choice(pool)
    return {
        "id": chosen[0],
        "angle_type": chosen[1],
        "template": chosen[2],
        "emotion": chosen[3],
        "example": chosen[4],
        "strength_score": chosen[5]
    }

def mark_angle_used(db_path: str, angle_id: int):
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE viral_angles SET last_used=?, usage_count=usage_count+1 WHERE id=?",
                 (datetime.now().isoformat(), angle_id))
    conn.commit()
    conn.close()

def score_hooks_locally(hooks: list[str]) -> str:
    """
    Score 2-3 hooks sans appel API. Retourne le meilleur.
    Critères : présence d'un chiffre (+2), longueur 6-12 mots (+1),
    mot interrogatif (+1), verbe d'action (+1), mot négatif/tension (+1).
    """
    import re
    action_verbs = ["arrête","évite","fais","crée","construit","découvre","comprends","réalise"]
    tension_words = ["jamais","erreur","piège","bloque","peur","perds","échoue","stagne"]

    def score(h):
        s = 0
        words = h.split()
        if re.search(r'\d', h): s += 2
        if 6 <= len(words) <= 12: s += 1
        if any(w in h.lower() for w in ["pourquoi","comment","quand","si","quel"]): s += 1
        if any(v in h.lower() for v in action_verbs): s += 1
        if any(t in h.lower() for t in tension_words): s += 1
        return s

    return max(hooks, key=score)
