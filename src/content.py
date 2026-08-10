from __future__ import annotations

import json
import random
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from google import genai

from .secrets import get_secret

PILLARS = [
    "Dignité", "Sagesse", "Libération", "Productivité", "Restauration relationnelle",
    "Provision Active", "Générosité",
]

BRAND_TAGS = ["#VoixDeProspéritéEnChrist", "#BusinessEnChrist", "#FoiEtTravail"]
PILLAR_TAGS = {
    "Dignité": ["#DignitéEnChrist", "#Valeur", "#Identité"],
    "Sagesse": ["#Sagesse", "#Discernement", "#ConseilDivin"],
    "Libération": ["#LibertéBiblique", "#NouveauDépart", "#Délivrance"],
    "Productivité": ["#Productivité", "#Excellence", "#Discipline"],
    "Restauration relationnelle": ["#Réconciliation", "#Pardon", "#Relations"],
    "Provision Active": ["#Provision", "#Pourvoyeur", "#FoiActive"],
    "Générosité": ["#Générosité", "#Partage", "#Bénédiction"],
}

TRUTH_LABELS = ["La vérité ?", "La vérité, c'est simple :", "Ce qu'il faut retenir :", "Le fond du sujet :"]
CAPTION_CLOSERS = [
    "Le détail t'attend en commentaire 👇",
    "La suite est en commentaire, vas-y 👇",
    "Dis-moi ce que tu en penses en commentaire 👇",
    "",
]

# Points génériques pour le générateur local : le nombre de points retenus doit
# TOUJOURS égaler le nombre annoncé dans le titre (voir _validate).
LOCAL_POINTS = [
    ("Commence avec ce qui t'est confié", "La fidélité se construit dans les petites responsabilités.", "Chez toi, choisis une action utile à terminer aujourd'hui."),
    ("Cherche la sagesse avant la précipitation", "Une décision paisible vaut mieux qu'une solution rapide sans discernement.", "Chez toi, prends un temps de prière et note tes options."),
    ("Fais du bien autour de toi", "La prospérité biblique produit du fruit qui bénit aussi les autres.", "Chez toi, encourage ou aide concrètement une personne cette semaine."),
    ("Garde tes engagements", "Tenir parole construit la confiance, avec les autres et avec Dieu.", "Chez toi, note tes promesses de la semaine et honore-les une par une."),
    ("Apprends à dire non", "Tout ce qui est bon n'est pas forcément ta priorité.", "Chez toi, refuse un engagement qui n'apporte rien à ta mission."),
    ("Médite la Parole avant d'agir", "Ce que tu remplis ton cœur en premier guide tes décisions.", "Chez toi, lis un verset le matin et laisse-le guider ta journée."),
    ("Investis dans les relations", "Ton réseau n'est pas qu'un carnet d'adresses : c'est un terrain de service.", "Chez toi, appelle quelqu'un pour prendre de ses nouvelles."),
    ("Gère ce que tu as, même peu", "La gestion de la petite somme prépare la confiance pour la grande.", "Chez toi, fais un état des lieux de tes finances de la semaine."),
    ("Agis pendant que c'est le jour", "L'occasion ne t'attend pas indéfiniment.", "Chez toi, avance aujourd'hui sur la tâche que tu remets depuis longtemps."),
    ("Entoure-toi de bons conseils", "La sagesse se reçoit dans l'humilité, pas dans l'isolement.", "Chez toi, demande l'avis d'un aîné de confiance avant de trancher."),
    ("Garde la paix dans les épreuves", "Dieu n'est pas absent quand c'est dur, il travaille dans le calme.", "Chez toi, remplace la plainte par une prière de gratitude."),
    ("Rends grâce en toute saison", "Un cœur reconnaissant garde la porte ouverte à la provision.", "Chez toi, écris trois choses pour lesquelles tu remercies Dieu aujourd'hui."),
    ("Travaille avec soin", "Le travail bien fait est une forme de culte.", "Chez toi, soigne le dernier détail de ton travail avant de le livrer."),
    ("Laisse Dieu agir à son rythme", "Ta précipitation n'accélère jamais Son plan, elle l'encombre.", "Chez toi, dépose un souci qui te presse et attends Sa paix."),
]


@dataclass
class Content:
    pillar: str
    title: str
    hook: str
    points: list[dict[str, str]]
    truth: str
    cta: str
    verse_reference: str
    topic: str
    decor: str
    image_prompt: str
    hashtags: list[str]

    @staticmethod
    def _pick(variants: list[str], title: str) -> str:
        return variants[sum(ord(c) for c in title) % len(variants)]

    @property
    def caption(self) -> str:
        closer = self._pick(CAPTION_CLOSERS, self.title)
        body = f"{self.title}\n\n{self.hook}"
        return f"{body}\n\n{closer}".strip() if closer else body

    @property
    def comment_text(self) -> str:
        points = "\n\n".join(
            f"{index}. {point['heading']}\n{point['body']}\n{point['application']}"
            for index, point in enumerate(self.points, 1)
        )
        label = self._pick(TRUTH_LABELS, self.title)
        return (
            f"{self.title}\n\n{points}\n\n{label}\n{self.truth}\n\n"
            f"📖 {self.verse_reference}\n\n{self.cta}\n\n{' '.join(self.hashtags)}"
        )

    def to_dict(self) -> dict:
        return asdict(self) | {"caption": self.caption, "comment_text": self.comment_text}


SYSTEM_PROMPT = """Tu écris pour la page Facebook chrétienne francophone « Voix de Prospérité en Christ ».
Réponds EXCLUSIVEMENT avec un objet JSON valide.

FONDEMENT THÉOLOGIQUE — LES 7 PILIERS DE LA PROSPÉRITÉ CHRÉTIENNE
Tout le contenu (titre, accroche, points, vérité, appel à l'action) doit s'enraciner dans
ces 7 piliers, comme le fit l'onction sur Jésus : « annoncer aux pauvres qu'en Dieu ils
peuvent être relevés spirituellement, mentalement, socialement et parfois matériellement ».
1. Dignité — bonne nouvelle aux pauvres : passer de la misère à la dignité. Le pauvre
   n'est pas défini par son manque ; en Christ il retrouve identité, valeur, espérance et
   une place dans le dessein de Dieu.
2. Sagesse — recevoir la sagesse pour sortir du manque : la prospérité biblique ne commence
   pas par l'argent mais par la sagesse, la discipline, la vision, le travail, la justice
   et la bonne gestion.
3. Libération — être libéré des blocages intérieurs : peur, fatalisme, honte, paresse,
   confusion, dépendances, mentalité de défaite ; l'onction vient casser ce qui captive.
4. Productivité — être rendu capable de produire : Dieu ne relève pas pour consommer mais
   pour faire fructifier ; compétence, créativité, entreprise, service utile, fécondité.
5. Restauration relationnelle — entrer dans des relations restaurées : famille, amitiés,
   communauté ; on peut manquer d'argent en manquant aussi de paix, de discipline ou de
   bons liens.
6. Provision Active — accès à la provision divine AVEC action humaine : portes ouvertes,
   idées, personnes, opportunités, faveur — mais il faut répondre par l'obéissance et
   l'effort.
7. Générosité — devenir à son tour une source pour d'autres : la vraie prospérité n'est
   pas l'accumulation égoïste ; elle permet de bénir, relever, financer, enseigner, servir.

RÈGLE D'OR — la prospérité ici n'est pas « avoir plus », mais devenir complet, utile et
capable de faire du bien autour de soi. Ne promets jamais un gain matériel garanti. Chaque
astuce, conseil ou principe doit relier la foi à une action concrète et responsable,
inspirée d'au moins un de ces 7 piliers.

FOCALISATION — UN pilier par post. Le « Pilier obligatoire » fourni dans l'invite est le
SEUL thème à développer : choisi aléatoirement, il doit rester le centre du post du début
à la fin. Ne MÉLANGE JAMAIS plusieurs piliers dans un même post : chaque point, exemple,
titre, accroche et application doit découler de ce pilier unique. Si un autre pilier
affleure, reformule pour rester fidèle au pilier imposé.

STYLE — écris en français ORAL, direct et chaleureux, comme un grand frère qui parle
à des amis sur Facebook/WhatsApp en Afrique francophone :
- phrases courtes, interpellations directes (« toi », « tu »), questions au lecteur ;
- expressions simples et parlantes du quotidien, pas de prose littéraire ni de ton de cours.

INTERDITS absolus — tournures de robot : « il est essentiel de », « il est important de »,
« n'oublions pas que », « en conclusion », « en résumé », « il convient de »,
« dans le monde d'aujourd'hui », « sans plus tarder », « en définitive ».
Interdit aussi : cascades d'émojis, « !!! », phrases à rallonge.

VARIATION — change de structure d'un post à l'autre : parfois une question d'accroche,
parfois une affirmation directe, parfois une petite scène de vie, parfois un défi.
Ne colle jamais le même moule (pas toujours titre-listicle, pas toujours « La vérité ? »).

CONTENU — bibliquement responsable et pratique. Ne promets jamais richesse, guérison
ou résultat garanti ; ne dénigre aucun groupe. Le titre fait 15 mots max, accrocheur
et humain. COHÉRENCE IMPÉRATIVE : si le titre annonce un nombre (« 5 pratiques »,
« 3 clés », « 7 principes »…), le nombre d'éléments dans "points" doit être
EXACTEMENT ce même nombre. 3 à 7 points, chaque point avec une application concrète
qui commence par « Chez toi, ... » (jamais « il faut » ni « vous devez »).

COMMENTAIRE DÉTAILLÉ — il est publié tel quel en commentaire : il doit se lire comme
un vrai message de grand frère sur les réseaux, PAS comme une dissertation. Points
courts et directs, phrases qui parlent au « tu », aucune tournure scolaire du type
« en conclusion », « ci-dessus », « nous pouvons constater que ». Le label avant la
vérité est choisi au hasard par le système, ne l'écris pas dans le JSON.

HASHTAGS — génère 4 à 6 hashtags VARIÉS, choisis selon le pilier et le sujet du jour
(jamais le même jeu fixe). Inclus toujours #VoixDeProspéritéEnChrist puis des tags en lien
avec le thème. Sans espaces, avec « # ».

DÉCOR — le champ "decor" décrit une scène premium pour l'image (sans personnes célèbres,
sans texte, sans logos). "image_prompt" traduit cette scène pour un générateur d'images.

Schéma JSON obligatoire :
{"pillar":"", "title":"", "hook":"", "topic":"", "verse_reference":"Livre 0:0",
"decor":"", "image_prompt":"", "points":[{"heading":"", "body":"", "application":""}],
"truth":"", "cta":"", "hashtags":["#...", "#..."]}"""


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _build_hashtags(pillar: str, topic: str, rng: random.Random) -> list[str]:
    """Hashtags dynamiques : base de marque + tags du pilier, tirés selon le sujet."""
    pool = list(PILLAR_TAGS.get(pillar, list(PILLAR_TAGS.values())[0]))
    rotated = rng.sample(pool, min(len(pool), 3))
    return BRAND_TAGS + rotated


class ContentGenerator:
    def __init__(self, database):
        self.database = database

    def generate(self, prompt: str | None = None) -> Content:
        exclusions = {field: sorted(self.database.recent_values(field))[-180:] for field in ("title", "topic", "verse_reference", "cta", "decor")}
        key = get_secret("gemini_api_key")
        if key:
            last_exc: Exception | None = None
            # Jusqu'à 5 brouillons Gemini. Si un brouillon est rejeté (doublon ou
            # nombre de points incohérent), on redonne la raison à Gemini pour
            # qu'il corrige explicitement, avant de basculer sur le brouillon local.
            for attempt in range(5):
                try:
                    return self._gemini(key, exclusions, avoid=str(last_exc) if last_exc else None, prompt=prompt)
                except Exception as exc:
                    last_exc = exc
            # A local draft keeps testing and recovery possible; publishing still records the source in logs.
            return self._local(exclusions, warning=str(last_exc))
        return self._local(exclusions)

    def _gemini(self, key: str, exclusions: dict[str, list[str]], avoid: str | None = None, prompt: str | None = None) -> Content:
        pillar = random.choice(PILLARS)
        system_prompt = prompt or SYSTEM_PROMPT
        prompt_text = f"{system_prompt}\nPilier obligatoire : {pillar}.\nÉléments interdits 90 jours : {json.dumps(exclusions, ensure_ascii=False)}"
        if avoid:
            prompt_text += (
                f"\nTon brouillon précédent a été rejeté pour ce motif : {avoid}.\n"
                "Corrige-le maintenant : choisis un AUTRE verset, une autre accroche, "
                "un autre appel à l'action, et vérifie que le nombre annoncé dans le "
                "titre égale exactement le nombre de points. Aucun élément interdit ci-dessus."
            )
        client = genai.Client(api_key=key)
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt_text)
        if avoid:
            prompt += (
                f"\nTon brouillon précédent a été rejeté pour ce motif : {avoid}.\n"
                "Corrige-le maintenant : choisis un AUTRE verset, une autre accroche, "
                "un autre appel à l'action, et vérifie que le nombre annoncé dans le "
                "titre égale exactement le nombre de points. Aucun élément interdit ci-dessus."
            )
        client = genai.Client(api_key=key)
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        raw = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(raw)
        data.setdefault("hashtags", _build_hashtags(data.get("pillar", pillar), data.get("topic", ""), random.Random(data.get("topic", ""))))
        content = Content(**{field: data[field] for field in Content.__dataclass_fields__})
        self._validate(content, exclusions)
        return content

    def _local(self, exclusions: dict[str, list[str]], warning: str | None = None) -> Content:
        """Deterministic no-API fallback intended for setup, tests and quota recovery."""
        index = len(exclusions["title"]) + 1
        last_error = warning or "générateur local"
        for _ in range(200):
            try:
                content = self._build_local(index)
                self._validate(content, exclusions)
                return content
            except ValueError as exc:
                last_error = str(exc)
                index += 1
        raise ValueError(f"Impossible de générer un contenu unique après 200 essais : {last_error}")

    def _build_local(self, index: int) -> Content:
        pillar = PILLARS[index % len(PILLARS)]
        themes = ["discipline fidèle", "vision de long terme", "gestion responsable", "paix dans les décisions", "service qui crée de la valeur", "générosité intentionnelle", "courage dans l'action"]
        theme = themes[index % len(themes)]
        topic = f"{pillar} — {theme} — {index}"
        # UN SEUL nombre pilote à la fois le titre et le nombre de points : jamais
        # deux sources indépendantes (le contrôle _validate le vérifie aussi).
        count = 3 + index % 5  # 3..7 points, dans la limite éditoriale
        title = f"{count} pratiques de {theme} : repère {index}"
        offset = index % (len(LOCAL_POINTS) - 7)
        points = [
            {"heading": heading, "body": body, "application": application}
            for heading, body, application in LOCAL_POINTS[offset:offset + count]
        ]
        return Content(
            pillar=pillar, title=title, hook="(Une fidélité discrète peut transformer ta manière d'avancer.)",
            topic=topic, verse_reference=f"Proverbes {(index % 31) + 1}:{(index // 31) + 1}",
            decor=["bureau élégant baigné de lumière dorée", "bibliothèque bleu marine et or", "montagnes majestueuses au lever du jour"][index % 3] + f", composition {index}",
            image_prompt="Scène éditoriale premium bleu marine et or, lumière naturelle, aucun texte, aucune marque.",
            points=points,
            truth="Dieu ne mesure pas seulement ce que tu possèdes, mais ce que ta fidélité produit dans ta vie et autour de toi.",
            cta=f"Quel point veux-tu appliquer cette semaine ? Écris-le en commentaire. ({index})",
            hashtags=_build_hashtags(pillar, topic, random.Random(topic)),
        )

    def _validate(self, content: Content, exclusions: dict[str, list[str]]) -> None:
        if content.pillar not in PILLARS or len(content.title.split()) > 15 or not (3 <= len(content.points) <= 7):
            raise ValueError("Le contenu généré ne respecte pas le format éditorial")
        announced = re.search(
            r"\b(\d{1,2})\s+(?:\w+\s+){0,2}(?:pratiques|conseils|principes|clés|cles|etapes|étapes|secrets|règles|regles|manières|manieres|façons|facons|pistes)\b",
            content.title, re.IGNORECASE,
        )
        if announced and int(announced.group(1)) != len(content.points):
            raise ValueError(
                "Le nombre annoncé dans le titre ne correspond pas au nombre de points développés"
            )
        for field in exclusions:
            if _clean(str(getattr(content, field))).casefold() in set(exclusions[field]):
                raise ValueError(f"Doublon sur 90 jours : {field}")
