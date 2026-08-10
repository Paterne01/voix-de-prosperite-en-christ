from __future__ import annotations

import json
import random
import re
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime

from google import genai

from .secrets import get_secret

PILLARS = [
    "Dignité", "Sagesse", "Libération", "Productivité", "Restauration relationnelle",
    "Provision Active", "Générosité",
]

BRAND_TAGS = ["#VoixDeProspéritéEnChrist", "#BusinessEnChrist", "#FoiEtTravail"]

# Dimension que la déclaration « clôture » à chaque post — reformulée à chaque
# génération (jamais la même phrase figée). Servent de structure de fermeture.
CLOSURE_DIMENSIONS = [
    "ton état spirituel", "tes pensées et tes décisions", "tes projets professionnels",
    "tes relations et ta famille", "ta santé intérieure", "tes finances et tes ressources",
    "ton impact autour de toi",
]

# CTA humains pour l'image du Format B (remplacent « Détails en commentaire »).
# Variés, choisis en local sans API ; l'anti-répétition 90 j est appliqué via
# le suivi SQLite comme pour le reste du contenu.
LOCAL_CTAS = [
    "Partage ça à quelqu'un qui en a besoin 🙏",
    "Envoie ça à un frère ou une sœur aujourd'hui ❤️",
    "Tague quelqu'un que Dieu est en train de relever",
    "Quelqu'un autour de toi a besoin d'entendre ça",
    "Répète cette parole à voix haute et crois-la",
    "Garde ce message sous la main cette semaine",
    "Bénis quelqu'un en lui partageant cette déclaration",
    "Ce soir, médite cette parole avant de dormir",
    "Confie cette parole à une personne qui doute encore",
    "Ouvre ton cœur et reçois cette déclaration aujourd'hui",
]

VERSES = [
    "Ésaïe 60:1", "Philippiens 4:13", "Proverbes 3:6", "Psaume 20:5",
    "Jérémie 29:11", "Romains 8:11", "Deutéronome 28:12", "Ésaïe 61:1",
    "Psaume 112:1", "Matthieu 6:33", "Proverbes 18:16", "Job 5:17",
]


@dataclass
class Declaration:
    pillar: str
    declaration: str
    closure: str
    cta: str
    verse_reference: str
    topic: str
    decor: str
    image_prompt: str
    hashtags: list[str]

    # ── adaptateurs vers l'interface d'édition commune ────────────────

    @property
    def title(self) -> str:
        return self.declaration

    @property
    def hook(self) -> str:
        return ""

    @property
    def caption(self) -> str:
        return f"{self.declaration}\n\n{self.closure}"

    @property
    def comment_text(self) -> str:
        return ""

    @property
    def points(self) -> list[dict[str, str]]:
        return []

    def to_dict(self) -> dict:
        return asdict(self) | {"caption": self.caption, "comment_text": self.comment_text}


SYSTEM_PROMPT_DECLARATION = """Tu écris des « déclarations prophétiques » pour la page chrétienne francophone « Voix de Prospérité en Christ ».
Réponds EXCLUSIVEMENT avec un objet JSON valide.

Un post « Déclaration prophétique » est une image + un texte bref : PAS de commentaire long,
PAS de liste de points. C'est une parole directe, au présent, que le lecteur prononce sur sa vie.

FONDEMENT THÉOLOGIQUE — LES 7 PILIERS DE LA PROSPÉRITÉ CHRÉTIENNE :
1. Dignité · 2. Sagesse · 3. Libération · 4. Productivité · 5. Restauration relationnelle ·
6. Provision Active · 7. Générosité.
La prospérité biblique n'est PAS « avoir plus » : c'est devenir complet, utile et capable de
faire du bien autour de soi, comme le fit l'onction sur Jésus. Ne promets JAMAIS un gain
matériel garanti, une guérison ou un résultat automatique.

FOCALISATION — UN pilier par texte. Le « Pilier obligatoire » fourni dans l'invite est le
SEUL thème à développer, sans mélange.

STYLE — français ORAL, direct, chaleureux, au « tu » (grand frère qui parle à des amis en
Afrique francophone). Phrases courtes. La déclaration se raconte au PRÉSENT, comme une
parole déjà en marche : « Je déclare que… », « Tu es… », « Aujourd'hui il se passe ceci… ».

CONTENU — « declaration » : le corps du texte, 2 à 4 phrases, 40 mots max. Il doit être
affirmatif, responsable, et inspirer action ET foi. Termine par un verset cité avec sa
référence exacte (ex. « Ésaïe 19:1 » — jamais sans la référence, jamais inventée au format
illisible). Le champ « closure » : une seule phrase courte (~15 mots) qui « clôture » le
texte en déclarant sur TOUT l'être du lecteur (état spirituel, décisions, relations,
finances, santé intérieure, projets, générosité) — reformulée à chaque post, jamais une
phrase figée, jamais de liste ni de « !!! ». Le champ « cta » : UNE phrase courte et
humaine (~8-12 mots), au « tu », qui invite à PARTAGER le message (ex. « Partage ça à
quelqu'un qui en a besoin 🙏 », « Envoie ça à un frère ou une sœur aujourd'hui ❤️ »,
« Tague quelqu'un que Dieu est en train de relever »). Le CTA est affiché sur l'image :
il doit être différent à chaque post — vérifie les « éléments interdits » fournis et
n'écris jamais le même CTA que les posts récents.

STYLE — PAS de commentaire long ni de liste. PAS de tournures robots : « il est essentiel
de », « n'oublions pas que », « en conclusion », « il convient de ». Pas de cascades d'émojis.
Chaque post change de structure (parfois « Je déclare », parfois « Aujourd'hui »,
parfois une question-réponse, parfois une petite scène de vie).

Photos — « decor » décrit une scène premium pour l'image (jamais de personnes célèbres, pas
de texte, pas de logos) ; « image_prompt » traduit la scène pour un générateur.

HASTAGS — 4 à 6 hashtags variés selon pilier/thème, incluant toujours
#VoixDeProspéritéEnChrist.

Schéma JSON obligatoire :
{"pillar":"", "declaration":"", "closure":"", "cta":"", "verse_reference":"Livre 0:0",
"topic":"", "decor":"", "image_prompt":"", "hashtags":["#…","#…"]}"""


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _build_hashtags(pillar: str, topic: str, rng: random.Random) -> list[str]:
    pool = ["#Déclaration", "#ParoleProphétique", "#Foi", "#Restauration", "#Provision"]
    rotated = rng.sample(pool, 3)
    return BRAND_TAGS + rotated


class DeclarationGenerator:
    def __init__(self, database):
        self.database = database

    def generate(self, prompt: str | None = None) -> Declaration:
        exclusions = {
            field: sorted(self.database.recent_values(field))[-50:]
            for field in ("title", "topic", "verse_reference", "cta")
        }
        key = get_secret("gemini_api_key")
        if key:
            last_exc: Exception | None = None
            for attempt in range(4):
                try:
                    return self._gemini(key, exclusions, avoid=str(last_exc) if last_exc else None, prompt=prompt)
                except Exception as exc:
                    last_exc = exc
            return self._local(exclusions, warning=str(last_exc))
        return self._local(exclusions)

    def _gemini(self, key: str, exclusions: dict[str, list[str]], avoid: str | None = None, prompt: str | None = None) -> Declaration:
        pillar = random.choice(PILLARS)
        system_prompt = prompt or SYSTEM_PROMPT_DECLARATION
        prompt_text = (
            f"{system_prompt}\n"
            f"Pilier obligatoire : {pillar}.\n"
            f"Éléments interdits 90 jours : {json.dumps(exclusions, ensure_ascii=False)}"
        )
        if avoid:
            prompt_text += (
                f"\nTon brouillon précédent a été rejeté pour ce motif : {avoid}.\n"
                "Corrige-le : prend un AUTRE verset, une AUTRE reformulation de « declarare »."
            )
        client = genai.Client(api_key=key)
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt_text)
        raw = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(raw)
        data.setdefault("hashtags", _build_hashtags(data.get("pillar", pillar), data.get("topic", ""), random.Random(data.get("topic", ""))))
        content = Declaration(**{field: data[field] for field in Declaration.__dataclass_fields__})
        self._validate(content, exclusions)
        return content

    def _local(self, exclusions: dict[str, list[str]], warning: str | None = None) -> Declaration:
        index = len(exclusions["topic"]) + 1
        last_error = warning or "générateur local de déclarations"
        for _ in range(400):
            try:
                content = self._build_local(index)
                self._validate(content, exclusions)
                return content
            except ValueError as exc:
                last_error = str(exc)
                index += 1
        raise ValueError(f"Impossible de générer une déclaration unique après 400 essais : {last_error}")

    def _build_local(self, index: int) -> Declaration:
        pillar = PILLARS[index % len(PILLARS)]
        plan = {
            "Dignité": "Tu es relevé et choisi ; ta valeur ne dépend pas de tes dettes.",
            "Sagesse": "Des cieux s'ouvrent sur tes décisions ; tu choisis avec discernement.",
            "Libération": "Ce qui te retenait se brise ; tu marches libre et léger.",
            "Productivité": "Tu produis ; chaque main qui plante récolte cent fois.",
            "Restauration relationnelle": "Les relations brisées se réparent ; la paix revient autour de toi.",
            "Provision Active": "La provision arrive ; les portes s'ouvrent et tu sais y entrer.",
            "Générosité": "Tu deviens une source ; ce que tu reçois, tu le bénis et le partages.",
        }[pillar]
        line = f"{plan} Aujourd'hui, cette parole se met en marche et il se passe quelque chose."
        dim = CLOSURE_DIMENSIONS[index % len(CLOSURE_DIMENSIONS)]
        closure = f"Je déclare la faveur de Dieu sur {dim}. Amen."
        cta = LOCAL_CTAS[index % len(LOCAL_CTAS)]
        return Declaration(
            pillar=pillar,
            declaration=line,
            closure=closure,
            cta=cta,
            verse_reference=VERSES[index % len(VERSES)],
            topic=f"{pillar} — déclaration — {index}",
            decor=["ciel au lever du jour doré et paisible", "fenêtre ouverte sur une lumière douce", "coucher de soleil serein au-dessus d'une vallée"][index % 3] + f", composition {index}",
            image_prompt="Scène éditoriale premium calme et dorée, lumière naturelle, aucun texte, aucune marque.",
            hashtags=_build_hashtags(pillar, str(index), random.Random(str(index))),
        )

    def _validate(self, content: Declaration, exclusions: dict[str, list[str]]) -> None:
        if content.pillar not in PILLARS:
            raise ValueError("Pilier inconnu pour la déclaration")
        if len(content.declaration.split()) > 55:
            raise ValueError("Déclaration trop longue")
        if not content.closure:
            raise ValueError("Déclaration sans phrase de clôture")
        if not content.cta:
            raise ValueError("Déclaration sans appel à l'action")
        for field in exclusions:
            if _clean(str(getattr(content, field))).casefold() in set(exclusions[field]):
                raise ValueError(f"Doublon sur 90 jours : {field}")