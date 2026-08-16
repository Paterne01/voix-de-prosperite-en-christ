from __future__ import annotations

import json
import random
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from .hf_text import generate_json as hf_generate_json
from .llm import generate_with_fallback, ordered_providers

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

# Types d'accroche possibles pour le premier post. Le système en choisit un au
# hasard (jamais deux posts consécutifs du même type) et le stocke en SQLite
# (colonne hook_type) comme les titres. L'IA reçoit le type imposé et produit
# une première phrase conforme.
HOOK_TYPES = [
    ("question_pain", "Une question qui fait mal"),
    ("constat_cache", "Un constat qui nomme une réalité cachée"),
    ("contre_intuitif", "Une déclaration contre-intuitive"),
    ("identification", "Un déclencheur d'identification"),
    ("chiffre", "Un chiffre ou fait inattendu"),
]
HOOK_STRUCTURE_EXAMPLES = {
    "question_pain": "Tu travailles dur depuis des années et tu te demandes encore pourquoi ça ne décolle pas ?",
    "constat_cache": "Beaucoup de gens prient pour sortir de la pauvreté mais ont peur en secret d'y croire vraiment.",
    "contre_intuitif": "Ce n'est pas ton manque d'argent qui te bloque. C'est ce que tu crois sur toi-même.",
    "identification": "Si tu as déjà honte de ta situation devant ta famille, ce post est pour toi.",
    "chiffre": "En Afrique, des milliers de personnes abandonnent chaque année à cause d'une seule croyance limitante.",
}

# Hashtags « génériques » servant uniquement à compléter une réponse de l'IA
# qui en aurait fourni moins de 5 (jamais pour en rajouter à une réponse complète).
_FALLBACK_HASHTAGS = [
    "#VoixDeProspéritéEnChrist", "#ProspéritéDivine", "#FoiEtTravail",
    "#ParoleDuJour", "#Foi",
]


def normalize_hashtags(hashtags, fallback: list[str] | None = None) -> list[str]:
    """Normalise une liste de hashtags à EXACTEMENT 5 éléments, sans doublon.

    - nettoie (espaces, '#', vides) ;
    - dédoublonne en gardant l'ordre ;
    - tronque à 5 si la réponse de l'IA en contient plus ;
    - complète avec des tags génériques de la page s'il y en a moins de 5.
    Jamais un post ne sort avec 6 hashtags ou plus.
    """
    pool = list(fallback) if fallback is not None else list(_FALLBACK_HASHTAGS)
    out: list[str] = []
    seen: set[str] = set()
    for tag in [*hashtags, *pool]:
        if len(out) >= 5:
            break
        token = str(tag).strip().lstrip("#").strip()
        if not token:
            continue
        cleaned = "#" + token
        if cleaned.casefold() in seen:
            continue
        seen.add(cleaned.casefold())
        out.append(cleaned)
    return out[:5]

TRUTH_LABELS = ["La vérité ?", "La vérité, c'est simple :", "Ce qu'il faut retenir :", "Le fond du sujet :"]
CAPTION_CLOSERS = [
    "Le détail t'attend en commentaire 👇",
    "La suite est en commentaire, vas-y 👇",
    "Dis-moi ce que tu en penses en commentaire 👇",
    "",
]

# Situations concrètes ajoutées au TITRE local : elles ancrent le post dans une
# réalité vécue (dettes, jugement des proches, prière sans réponse…) et
# multiplient les combinaisons de titres uniques (focus × angle × nombre).
LOCAL_ANGLES = {
    "Dignité": [
        "quand la honte te tient à l'écart", "face au jugement des proches",
        "quand tes finances ne décollent pas", "malgré ce que tu n'as pas accompli",
        "quand tu te sens invisible", "après une chute qui t'a fait douter",
        "quand on ne te valorise pas", "au travail, là où personne ne te remarque",
        "quand ta famille doute de toi", "devant un miroir que tu évites",
    ],
    "Sagesse": [
        "avant de signer un contrat", "quand tout le monde te presse de décider",
        "face à une offre trop belle", "avant de dépenser",
        "quand tu dois trancher seul", "après une erreur que tu veux éviter de répéter",
        "au moment de donner un conseil", "quand l'argent parle trop fort",
        "face à un choix qui engage demain", "quand la précipitation te guette",
    ],
    "Libération": [
        "quand la peur te paralyse", "après des années de blocage",
        "quand la même pensée revient sans cesse", "face à l'échec qui t'a marqué",
        "quand tu portes encore le passé", "au moment de recommencer à zéro",
        "quand on t'a condamné trop tôt", "quand tu crois le mensonge sur toi",
        "au réveil, avant que le poids revienne", "quand le regard des autres t'enchaîne",
    ],
    "Productivité": [
        "quand ta journée t'échappe", "face à la tâche que tu remets",
        "quand rien ne semble avancer", "au milieu de trop d'occupations",
        "quand tu veux vraiment produire", "avant de perdre encore une semaine",
        "quand ton bureau te fait fuir", "au moment où l'énergie faiblit",
        "quand les résultats tardent", "avant d'abandonner un projet qui compte",
    ],
    "Restauration relationnelle": [
        "quand la maison est en silence", "après une dispute qui a tout cassé",
        "face à un proche qui s'éloigne", "quand le pardon semble impossible",
        "au milieu d'une famille divisée", "quand tu as honte de renouer",
        "quand l'orgueil tient la porte fermée", "au moment où les mots manquent",
        "quand chacun attend que l'autre cède", "après une trahison que tu portes",
    ],
    "Provision Active": [
        "quand les portes semblent fermées", "face à une opportunité qui passe",
        "quand tu as tout essayé", "au moment où le besoin se fait sentir",
        "quand la faveur tarde", "avant de renoncer à une porte ouverte",
        "quand tes efforts ne paient pas encore", "au point de croire que c'est fini",
        "quand l'offre paraît trop risquée", "face à une porte que tu oses à peine frapper",
    ],
    "Générosité": [
        "quand tu as peu mais veux donner", "face à quelqu'un dans le besoin",
        "quand tout le monde te demande", "au moment d'ouvrir ta main",
        "quand tu veux aider sans t'appauvrir", "avant de garder pour toi seul",
        "quand on profite de ta bonté", "au moment où donner coûte vraiment",
        "quand tu doutes que ton geste compte", "face à un besoin qui te dépasse",
    ],
}

# Vérités PAR PILIER pour le générateur local : une vérité figée unique pour
# tous les piliers rendait chaque commentaire identique. Désormais chaque pilier
# dispose de plusieurs vérités, choisies selon le titre pour varier à chaque post.
LOCAL_TRUTHS = {
    "Dignité": [
        "Dieu ne mesure pas ce que tu possèdes, mais qui tu es en lui : cher, appelé et relevé.",
        "Ta valeur ne dépend ni de ton compte, ni de l'avis des autres : elle vient de Dieu.",
        "La dignité n'est pas un statut que tu attends, c'est une identité que tu reçois.",
    ],
    "Sagesse": [
        "Une bonne décision vaut mieux que dix bons plans sans discernement.",
        "La vraie sagesse ne consiste pas à tout savoir, mais à demander avant d'agir.",
        "Dieu ne te demande pas de tout maîtriser, seulement de le consulter d'abord.",
    ],
    "Libération": [
        "La peur n'a d'autorité sur toi que celle que tu lui donnes.",
        "Ce qui te retenait n'est pas plus fort que la parole qui t'affranchit.",
        "Ta liberté commence le jour où tu arrêtes de croire le mensonge qui t'enchaîne.",
    ],
    "Productivité": [
        "Dieu ne bénit pas seulement ce que tu pries, il bénit ce que tu fais.",
        "La fidélité dans les petites choses prépare les grandes confiances.",
        "Un pas fait aujourd'hui vaut mieux qu'un grand projet remis pour toujours.",
    ],
    "Restauration relationnelle": [
        "La prospérité sans paix autour de toi est une maison riche mais vide.",
        "Pardonner, ce n'est pas effacer la faute, c'est reprendre ta liberté.",
        "Dieu répare les relations, mais il te demande de faire le premier pas.",
    ],
    "Provision Active": [
        "Les portes s'ouvrent pour ceux qui sont déjà en train de marcher.",
        "La provision de Dieu demande souvent une main qui se lève et qui frappe.",
        "Ce n'est pas la porte qui manque, c'est parfois le courage de frapper.",
    ],
    "Générosité": [
        "Ce qui circule se multiplie ; ce qui reste enfermé se dessèche.",
        "La vraie prospérité se mesure à ce que tu rends possible autour de toi.",
        "On ne perd jamais en donnant : on sème ce qui reviendra.",
    ],
}

# CTA variés pour le générateur local : remplace le CTA figé « Quelle clé… (N) »
# qui apparaissait à l'identique sur chaque post de secours. Chaque gabarit
# contient `{focus}` pour garantir des CTA uniques selon le focus du post.
LOCAL_CTAS = {
    "Dignité": [
        "Quelle parole veux-tu croire sur toi pour {focus} ? Dis-le en commentaire.",
        "Écris ce soir une vérité que tu veux retenir sur {focus}.",
        "Prends une minute pour te relire à voix haute : {focus} compte pour Dieu.",
        "Qu'est-ce qui doit changer dans ta façon de voir {focus} cette semaine ?",
        "Tage quelqu'un qui a besoin d'entendre ceci sur {focus}.",
    ],
    "Sagesse": [
        "Quelle décision veux-tu confier à Dieu avant d'agir sur {focus} ? Réponds en commentaire.",
        "Note la question que tu dois poser avant de trancher sur {focus}.",
        "Prends le temps de demander conseil avant d'avancer sur {focus}.",
        "Quelle fausse solution dois-tu refuser pour {focus} cette semaine ?",
        "Partage la leçon que {focus} t'a déjà appris.",
    ],
    "Libération": [
        "Qu'est-ce que tu décides de laisser partir aujourd'hui pour avancer sur {focus} ?",
        "Partage en commentaire une chaîne dont tu veux être libéré sur {focus}.",
        "Fais aujourd'hui la chose que tu remets par peur sur {focus}.",
        "Quelle pensée te retient encore sur {focus} ? Nomme-la et brise-la.",
        "Qui veux-tu remercier pour t'avoir aidé à progresser sur {focus} ?",
    ],
    "Productivité": [
        "Quelle tâche termines-tu aujourd'hui pour {focus} ? Engage-toi en commentaire.",
        "Choisis UNE petite action et fais-la dès maintenant pour {focus}.",
        "Note la promesse que tu veux tenir pour {focus} cette semaine.",
        "Quelle habitude veux-tu instaurer pour {focus} ?",
        "Dis-moi le progrès que tu veux voir sur {focus} d'ici dimanche.",
    ],
    "Restauration relationnelle": [
        "Quelle relation veux-tu réparer pour {focus} cette semaine ?",
        "Envoie le message de réconciliation que tu remets sur {focus}.",
        "Qui veux-tu appeler juste pour prendre de ses nouvelles, autour de {focus} ?",
        "Quelle parole douce peux-tu dire aujourd'hui pour {focus} ?",
        "Qui veux-tu bénir malgré la dispute, sur {focus} ?",
    ],
    "Provision Active": [
        "Quelle porte veux-tu frapper cette semaine pour {focus} ?",
        "Quel pas concret fais-tu aujourd'hui vers {focus} ?",
        "Dis-moi en commentaire l'action que tu engages pour {focus} dès maintenant.",
        "Quelle ressource négligée peux-tu faire grandir pour {focus} ?",
        "Quelle opportunité dois-tu saisir pour {focus} avant la fin du mois ?",
    ],
    "Générosité": [
        "Qui peux-tu bénir cette semaine, autour de {focus} ?",
        "Fais un geste de bonté que personne ne verra, pour {focus}.",
        "Quelle personne autour de toi peux-tu élever sur {focus} ?",
        "Quel conseil peux-tu partager gratuitement pour aider quelqu'un sur {focus} ?",
        "Quelle porte peux-tu ouvrir pour quelqu'un, en lien avec {focus} ?",
    ],
}

# Points pour le générateur local : banque PAR PILIER, pour que le commentaire
# reste toujours lié au point du jour ET au texte affiché sur l'image (titre +
# accroche). Le nombre de points retenus doit TOUJOURS égaler le nombre annoncé
# dans le titre (voir _validate). Vocabulaire oral façon réseaux sociaux (« toi »,
# « Chez toi, … ») comme le prompt IA.
LOCAL_BANK = {
    "Dignité": [
        ("Retrouve ta valeur en Christ", "Ton manque ne définit pas qui tu es : tu es cher, appelé et relevé par Dieu.", "Chez toi, écris ce soir trois vérités sur ta valeur et lis-les à voix haute."),
        ("Arrête de te comparer aux autres", "La comparaison vole ta paix et ton énergie, pas tes résultats.", "Chez toi, ferme les réseaux matière pour te concentrer sur TON avancement."),
        ("Refuse les étiquettes du passé", "Ce que les autres ont dit sur toi n'est pas le dernier mot de Dieu.", "Chez toi, note une étiquette qu'on t'a collée et remplace-la par une vérité biblique."),
        ("Traite-toi avec respect", "Ta dignité se voit dans la façon dont tu parles de toi et à toi.", "Chez toi, remplace une parole négative sur toi par une parole de bénédiction."),
        ("Porte la tête haute", "La honte ne rend personne plus fort ; l'orgueil sain si.", "Chez toi, viens aujourd'hui avec une posture digne, même si tes finances tardent."),
        ("Agis en enfant de Dieu", "Ton identité précède ta situation : tu n'es pas défini par ton compte en banque.", "Chez toi, accomplit une tâche avec l'assurance d'un enfant aimé de Dieu."),
        ("Sors de la mentalité d'indigent", "Dieu avait un plan pour toi bien avant ta naissance.", "Chez toi, médite Ésaïe 61:1-2 et demande ce que Dieu pense de toi."),
        ("Ne te défini pas par ce que tu n'as pas", "Ce qui te manque ne dit rien de ce que tu es en Christ.", "Chez toi, liste ce que tu as reçu de Dieu et pas seulement ce qui te manque."),
        ("Respecte ta valeur devant les autres", "Ta manière de te présenter enseigne aux autres comment te traiter.", "Chez toi, arrête de te minimiser quand on te demande qui tu es."),
        ("Marche sans mendier", "Tu n'es pas né pour tendre la main, mais pour bâtir et pour servir.", "Chez toi, refuse aujourd'hui la posture de l'inférieur et exerce ton autorité."),
        ("Sois fier de ton origine", "Dieu écrit ton histoire : tu n'as pas à en avoir honte.", "Chez toi, remercie Dieu pour le chemin parcouru, même modeste."),
        ("Occupe ta place", "Chaque enfant de Dieu a une place qui n'attend que lui.", "Chez toi, occupe une responsabilité que tu fuyais par manque d'estime."),
    ],
    "Sagesse": [
        ("Cherche la sagesse avant la précipitation", "Une décision paisible vaut mieux qu'une solution rapide sans discernement.", "Chez toi, prends un temps de prière et note tes options."),
        ("Apprends à dire non", "Tout ce qui est bon n'est pas forcément ta priorité.", "Chez toi, refuse un engagement qui n'apporte rien à ta mission."),
        ("Médite la Parole avant d'agir", "Ce que tu remplis ton cœur en premier guide tes décisions.", "Chez toi, lis un verset le matin et laisse-le guider ta journée."),
        ("Entoure-toi de bons conseils", "La sagesse se reçoit dans l'humilité, pas dans l'isolement.", "Chez toi, demande l'avis d'un aîné avant de trancher."),
        ("Compte avant de souscrire", "S'endetter pour « faire comme les autres » est un piège classique.", "Chez toi, fais le calcul complet avant d'accepter un crédit."),
        ("Gère ce que tu as, même peu", "La gestion honnête de la petite somme prépare la grande.", "Chez toi, fais un état des lieux de tes finances de la semaine."),
        ("Investis dans ce qui compte", "Tout investissement ne produit pas du fruit ; choisis avec discernement.", "Chez toi, note ce qui rapporte vraiment et coupe ce qui te draine."),
        ("Questionne avant d'accepter", "Une question simple évite des années de regret.", "Chez toi, pose la question que tu évites avant de signer."),
        ("N'apprends pas seul", "La sagesse des autres te fait gagner du temps.", "Chez toi, lis un livre ou écoute quelqu'un qui a réussi là où tu veux aller."),
        ("Fais silence avant de répondre", "La réponse précipitée envenime ; la parole réfléchie apaise.", "Chez toi, avant ta prochaine décision, accorde-toi une nuit de réflexion."),
        ("Choisis tes batailles", "Tout combat n'est pas pour toi ; ne dépense pas ton énergie partout.", "Chez toi, note ce qui mérite vraiment ton temps cette semaine."),
        ("Crains Dieu au lieu de craindre l'échec", "La crainte de Dieu vaut mieux que mille plans humains.", "Chez toi, demande à Dieu la priorité avant d'organiser ta journée."),
    ],
    "Libération": [
        ("Garde la paix dans les épreuves", "Dieu travaille dans le calme, pas dans la panique.", "Chez toi, remplace la plainte par une prière de gratitude."),
        ("Coupe avec la peur de l'échec", "La peur d'échouer t'a plus bloqué que l'échec lui-même.", "Chez toi, fais aujourd'hui la chose que tu remets par crainte."),
        ("Laisse tomber la honte", "La honte t'isole ; la vérité te libère.", "Chez toi, confie à une personne sûre ce que tu caches depuis longtemps."),
        ("Brûle les pensées limitantes", "« Je n'y arriverai jamais » est une voix, pas une fatalité.", "Chez toi, remplace cette pensée par une parole de foi concrète."),
        ("Pardonne pour avancer libre", "L'amertume est une chaîne que tu portes contre toi-même.", "Chez toi, libère une personne par le pardon, en prière."),
        ("Reprends la maîtrise de ta journée", "Le chaos mental se dissout dans les bonnes habitudes.", "Chez toi, fixe ton lever et une priorité unique pour demain."),
        ("Sors du fatalisme", "Ton histoire ne détermine pas ton avenir.", "Chez toi, écris une décision que tu remettais par résignation."),
        ("Tranche avec les mauvaises habitudes", "Une habitude est un chemin ; choisis lequel tu empruntes chaque jour.", "Chez toi, identifie l'habitude qui te vole et remplace-la dès ce soir."),
        ("Refuse la mentalité de victime", "Les circonstances existent, mais elles ne gouvernent plus ta vie.", "Chez toi, arrête de raconter ton problème et commence à décrire ta solution."),
        ("Délivre-toi du besoin d'approbation", "Tu n'as pas besoin que tout le monde valide pour avancer.", "Chez toi, fais une bonne action sans en parler à personne."),
        ("Ne vis plus dans le passé", "Dieu fait une chose nouvelle ; arrête de regarder en arrière.", "Chez toi, écris ce que tu laisses derrière toi aujourd'hui."),
        ("Brise le cycle du blocage", "Le même problème répété a une même cause : il est temps de la nommer.", "Chez toi, nomme un blocage récurrent et demande à Dieu la sortie."),
    ],
    "Productivité": [
        ("Commence avec ce qui t'est confié", "La fidélité se construit dans les petites responsabilités.", "Chez toi, choisis une action utile à terminer aujourd'hui."),
        ("Garde tes engagements", "Tenir parole construit la confiance, avec les autres et avec Dieu.", "Chez toi, note tes promesses de la semaine et honore-les une par une."),
        ("Agis pendant que c'est le jour", "L'occasion ne t'attend pas indéfiniment.", "Chez toi, avance sur la tâche que tu remets depuis longtemps."),
        ("Travaille avec soin", "Le travail bien fait est une forme de culte.", "Chez toi, soigne le dernier détail de ton travail avant de le livrer."),
        ("Termine ce que tu commences", "Un projet fini vaut mieux que dix projets commencés.", "Chez toi, clos un petit dossier resté en suspens cette semaine."),
        ("Produis avant de consommer", "Dieu te rend capable de créer, pas seulement d'acheter.", "Chez toi, fais quelque chose de tes mains qui peut servir quelqu'un."),
        ("Respecte tes heures", "La discipline des horaires change la face de ton business.", "Chez toi, bloque un créneau de travail profond pour demain."),
        ("Organise avant d'exécuter", "Le désordre mange ton temps ; un plan simple le libère.", "Chez toi, écris demain matin tes trois priorités sur un papier."),
        ("Apprends chaque jour", "Compétence d'aujourd'hui, revenus de demain.", "Chez toi, consacre trente minutes à apprendre quelque chose d'utile."),
        ("Sors de la consommation passive", "Ce que tu consommes chaque jour façonne ce que tu produis.", "Chez toi, échange un divertissement contre une formation cette semaine."),
        ("Fais moins, mais fais-le bien", "La qualité attire des résultats que la quantité ne donne pas.", "Chez toi, choisis un domaine et vise l'excellence au lieu de l'à-peu-près."),
        ("Mesure tes progrès", "Ce qu'on ne mesure pas ne progresse pas.", "Chez toi, note ce soir ce que tu as réellement accompli aujourd'hui."),
    ],
    "Restauration relationnelle": [
        ("Investis dans les relations", "Ton réseau n'est pas un carnet d'adresses : c'est un terrain de service.", "Chez toi, appelle quelqu'un pour prendre de ses nouvelles."),
        ("Demande pardon le premier", "Un cœur humble répare ce que l'orgueil a cassé.", "Chez toi, envoie le message de réconciliation que tu remets."),
        ("Écoute avant de juger", "Beaucoup de disputes meurent quand on écoute vraiment.", "Chez toi, écoute quelqu'un sans l'interrompre, puis réponds avec douceur."),
        ("Bénis ceux qui t'ont blessé", "La bénédiction désarme les conflits et t'affranchit.", "Chez toi, prie pour une personne avec qui tu es en froid."),
        ("Choisis bien ton entourage", "Tes fréquentations orientent tes décisions.", "Chez toi, rapproche-toi de quelqu'un qui t'élève, et protège ta paix."),
        ("Garde la paix de ta maison", "La prospérité sans paix familiale est une prison dorée.", "Chez toi, crée un moment de qualité avec tes proches cette semaine."),
        ("Sois quelqu'un à qui on peut se confier", "La confiance attire les opportunités et les bénédictions.", "Chez toi, garde le secret qu'on t'a confié et reviens vers la personne."),
        ("Parle avec des mots qui réparent", "La parole peut casser en un instant ce qui s'est bâti en des années.", "Chez toi, choisis des mots doux avant la prochaine discussion difficile."),
        ("Ne rumine pas les offenses", "Ruminer le passé te fait payer deux fois.", "Chez toi, décide ce soir de lâcher une offense que tu ressasses."),
        ("Rapproche-toi de ta famille", "La bénédiction commence dans la maison avant de s'étendre dehors.", "Chez toi, appelle un parent que tu négliges depuis longtemps."),
        ("Réconcilie avant de négocier", "Les affaires avancent quand les relations sont réparées.", "Chez toi, règle un différend avant de conclure un accord."),
        ("Pardonne sans attendre de excuses", "Pardonner n'est pas attendre qu'on le mérite : c'est te libérer.", "Chez toi, pardonne aujourd'hui, même si l'autre ne s'excuse pas."),
    ],
    "Provision Active": [
        ("Réponds par l'action à la provision", "Dieu ouvre les portes ; tes pas les traversent.", "Chez toi, fais aujourd'hui le pas concret que la porte exige."),
        ("Prépare le terrain avant la moisson", "La provision tombe sur un sol déjà travaillé.", "Chez toi, prépare ton CV, ton offre ou ton lieu avant la porte."),
        ("Lève la main quand l'opportunité passe", "Beaucoup voient la porte sans oser frapper.", "Chez toi, postule ou présente ton idée cette semaine."),
        ("Fais fructifier ce qui t'est donné", "Dieu te confie, puis tu multiplies ; c'est la règle des talents.", "Chez toi, prends une ressource que tu négliges et commence à la faire grandir."),
        ("Mets de l'ordre dans tes finances", "La faveur de Dieu aime les cœurs et les comptes ordonnés.", "Chez toi, établis un premier budget simple ce week-end."),
        ("Reconnais les aides de Dieu", "La provision passe aussi par les personnes que Dieu t'envoie.", "Chez toi, remercie quelqu'un qui t'a ouvert une porte."),
        ("Sème des graines d'action", "La foi sans action est un chèque jamais déposé.", "Chez toi, effectue la petite action que tu repousses depuis des semaines."),
        ("Ouvre l'œil aux portes ouvertes", "La provision passe souvent là où tu ne regardes pas.", "Chez toi, prête attention à une opportunité que tu ignorais."),
        ("Frappe avec persévérance", "La porte s'ouvre parfois après plusieurs frappes.", "Chez toi, retente une démarche refusée, avec une approche améliorée."),
        ("Associe compétence et prière", "La faveur divine et le savoir-faire avancent ensemble.", "Chez toi, améliore une compétence utile à ta prochaine porte."),
        ("Sois visible pour ta provision", "Qui ne se montre pas ne se voit pas confier.", "Chez toi, fais connaître ton offre à une personne de plus."),
        ("Ne méprise pas les petits commencements", "La grande provision commence souvent par une petite obéissance.", "Chez toi, fais bien la petite chose confiée aujourd'hui."),
    ],
    "Générosité": [
        ("Fais du bien autour de toi", "La prospérité biblique produit du fruit qui bénit aussi les autres.", "Chez toi, encourage ou aide concrètement une personne cette semaine."),
        ("Partage ce que tu as reçu", "La bénédiction grandit quand elle circule.", "Chez toi, donne du temps ou une ressource à quelqu'un dans le besoin."),
        ("Deviens une source", "Tu es appelé à devenir celui qui pourvoit, pas seulement celui qui reçoit.", "Chez toi, identifie une personne à qui ton savoir ou ton savoir-faire profiteraient."),
        ("Donne avec joie", "Dieu aime celui qui donne joyeusement, même peu.", "Chez toi, propose une aide sans attendre de retour."),
        ("Élève quelqu'un avec toi", "La vraie prospérité fait monter les autres avec elle.", "Chez toi, forme quelqu'un sur une compétence que tu maîtrises."),
        ("Sème d'abord chez les tiens", "La générosité commence dans ta maison.", "Chez toi, bénis un membre de ta famille de façon concrète."),
        ("Bénis sans calcul", "Le cœur généreux ne compte pas avant de donner.", "Chez toi, fais aujourd'hui un geste de bonté que personne ne verra."),
        ("Donne une chance à quelqu'un", "Chaque main tendue peut changer une vie entière.", "Chez toi, recommande ou ouvre une porte à quelqu'un qui en a besoin."),
        ("Sois généreux de tes conseils", "Le temps donné vaut parfois plus que l'argent.", "Chez toi, partage une leçon apprise avec quelqu'un qui débute."),
        ("Préserve la dignité en donnant", "Le don discret honore ; le don humiliant blesse.", "Chez toi, aide quelqu'un d'une manière qui préserve sa fierté."),
        ("Fais grandir la générosité chez tes enfants", "Ce que tu leur apprends à partager leur sera rendu centuple.", "Chez toi, implique tes proches dans un geste de partage cette semaine."),
        ("Ne repousse pas le pauvre", "Prêter main-forte au faible, c'est prêter à Dieu lui-même.", "Chez toi, tends la main à quelqu'un que tout le monde évite."),
    ],
}

# Focus du post local : phrases concrètes liant le titre au pilier (sert aussi
# d'amorce au commentaire pour qu'il suive l'image). Plusieurs focus par pilier
# pour garantir des titres humains UNIQUES sans « repère N » technique.
LOCAL_FOCUSES = {
    "Dignité": ["ta dignité en Christ", "ta valeur retrouvée", "ta place dans le dessein de Dieu", "sortir de la mentalité d'indigent", "parler et agir en enfant de Dieu", "te relever de la misère à la dignité", "répondre à ton appel", "renoncer à t'effacer"],
    "Sagesse": ["la sagesse qui sort du manque", "les décisions éclairées", "la bonne gestion de ce que tu as", "apprendre avant de s'engager", "compter le coût en prière", "recevoir la sagesse pour sortir du manque", "consulter avant de décider", "refuser les fausses solutions"],
    "Libération": ["ta libération des blocages", "briser la peur de l'échec", "la fin des pensées limitantes", "reprendre la maîtrise de ta journée", "la paix au cœur des épreuves", "être libéré des blocages intérieurs", "couper avec le fatalisme", "marcher sans la honte"],
    "Productivité": ["ta capacité à produire", "les fruits de tes mains", "fidèle dans les petites choses", "terminer ce que tu commences", "produire avant de consommer", "être rendu capable de produire", "bâtir dans la discipline", "agir pendant qu'il fait jour"],
    "Restauration relationnelle": ["tes relations restaurées", "la paix de ta maison", "pardonner pour avancer", "un réseau qui t'élève", "réparer avant de recommencer", "entrer dans des relations restaurées", "renouer avec ta famille", "te réconcilier avec ton passé"],
    "Provision Active": ["ta provision avec action", "les portes que Dieu ouvre", "répondre par l'obéissance", "préparer le terrain de ta moisson", "faire fructifier ce qui t'est donné", "l'accès à une provision avec action humaine", "frapper à la bonne porte", "saisir l'opportunité qui passe"],
    "Générosité": ["devenir une source pour les autres", "la générosité qui multiplie", "bénir autour de toi", "élever quelqu'un avec toi", "donner avec joie", "devenir à ton tour une source", "partager ce que tu as reçu", "semer pour les autres"],
}


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
    hook_type: str = ""
    engagement_score: int | None = None

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
        # Le commentaire démarre en reprenant l'accroche de l'image : le lecteur
        # du réseau retrouve immédiatement le texte qu'il a sous les yeux, puis
        # reçoit le développement. Cohérence image ↔ commentaire garantie.
        points = "\n\n".join(
            f"{index}. {point['heading']}\n{point['body']}\n{point['application']}"
            for index, point in enumerate(self.points, 1)
        )
        label = self._pick(TRUTH_LABELS, self.title)
        intro = self.hook.rstrip(" ?!") if self.hook else self.title
        return (
            f"{self.title}\n\n« {intro} »\n\n{points}\n\n{label}\n{self.truth}\n\n"
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
- expressions simples et parlantes du quotidien, pas de prose littéraire ni de ton de cours ;
- rythme VARIÉ : alterne question, affirmation, scène de vie, défi — jamais deux posts
  avec le même moule d'accroche. L'accroche (premier post) nomme une DOULEUR RÉELLE que le
  lecteur vit (honte financière, comparaison, peur de l'échec, prières sans réponse,
  jugement des proches, travail sans résultat visible) et le touche AVANT de lui donner
  la solution.

ACCROCHE IMPOSÉE — le champ « hook » est le premier message visible. Le type d'accroche
est IMPOSÉ par le système (question_pain, constat_cache, contre_intuitif, identification,
chiffre) : respecte-le ÉXACTEMENT, sans le nommer. Le hook fait 20 mots max, nomme la
douleur du lecteur, et se termine par une question ou par un deux-points qui donne envie
de lire la suite. Exemples par type manipulés spirituellement mais jamais accusateurs :
- question_pain : « Tu travailles dur depuis des années et tu te demandes encore pourquoi ça ne décolle pas ? »
- constat_cache : « Beaucoup prient pour sortir du manque, mais ont peur en secret d'y croire vraiment. »
- contre_intuitif : « Ton blocage n'est pas ton manque d'argent : c'est ce que tu crois sur toi-même. »

INTERDITS absolus — tournures de robot : « il est essentiel de », « il est important de »,
« n'oublions pas que », « en conclusion », « en résumé », « il convient de »,
« dans le monde d'aujourd'hui », « sans plus tarder », « en définitive », « n'hésite pas à »,
« j'espère que ». Interdit aussi : cascades d'émojis, « !!! », phrases à rallonge,
listes numérotées dans la légende, promesses de richesse ou de guérison garantie.

VARIATION — change de structure d'un post à l'autre : parfois une question d'accroche,
parfois une affirmation directe, parfois une petite scène de vie, parfois un défi.
Ne colle jamais le même moule (pas toujours titre-listicle, pas toujours « La vérité ? »).

CTA PRÉCIS — le champ « cta » est UN appel à l'action précis, actionnable et différent
à chaque post, jamais « partage si tu veux ». Adapte-le au contenu :
- défi → demande une action concrète de la semaine (ex. « Écris aujourd'hui une tâche que
  tu remets depuis des mois, accomplis-la d'ici dimanche. ») ;
- leçon → demande une décision ou un changement à mettre en pratique ;
- encouragement → demande de citer une personne qui a besoin de cette parole (partage ciblé) ;
- question → pose une vraie question de réflexion à laquelle le lecteur répond en commentaire.
2 phrases max. Aucune promesse de résultat matériel garanti.

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

HASHTAGS — génère EXACTEMENT 5 hashtags VARIÉS, choisis selon le pilier et le sujet du
jour (jamais le même jeu fixe). Inclus toujours #VoixDeProspéritéEnChrist puis des tags
en lien avec le thème. Sans espaces, avec « # ». JAMAIS plus de 5, JAMAIS moins de 5.

DÉCOR — le champ "decor" décrit une scène premium pour l'image (sans personnes célèbres,
sans texte, sans logos). "image_prompt" traduit cette scène pour un générateur d'images.

Schéma JSON obligatoire :
{"pillar":"", "title":"", "hook":"", "topic":"", "verse_reference":"Livre 0:0",
"decor":"", "image_prompt":"", "points":[{"heading":"", "body":"", "application":""}],
"truth":"", "cta":"", "hashtags":["#...", "#..."]}"""


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _tokenize(value: str) -> set[str]:
    """Ensemble de mots-clés significatifs d'un texte (minuscules, sans mots vides)."""
    stopwords = {
        "pour", "de", "du", "des", "le", "la", "les", "un", "une", "et", "en", "au", "aux",
        "sur", "que", "qui", "dans", "ce", "ces", "avec", "sans", "pas", "tu", "ta", "ton",
        "tes", "toi", "ton", "tes", "c'est", "ceci", "n'est", "ne", "se", "sa", "son", "tes",
    }
    words = re.findall(r"\b[a-z0-9]{3,}\b", value.casefold())
    return {w for w in words if w not in stopwords}


def _jaccard(a: set[str], b: set[str]) -> float:
    """Similarité de Jaccard entre deux ensembles de mots (0..1)."""
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _too_close(title: str, recent_titles: set[str], threshold: float = 0.55) -> bool:
    """Vrai si le titre est trop proche d'un titre publié récemment (même jour
    ou jours passés) — évite que deux posts quasi identiques se suivent."""
    new_tokens = _tokenize(title)
    if not new_tokens:
        return False
    for recent in recent_titles:
        recent_tokens = _tokenize(recent)
        if _jaccard(new_tokens, recent_tokens) >= threshold:
            return True
    return False


def _build_hashtags(pillar: str, topic: str, rng: random.Random) -> list[str]:
    """Hashtags dynamiques : base de marque + tags du pilier, EXACTEMENT 5."""
    pool = list(PILLAR_TAGS.get(pillar, list(PILLAR_TAGS.values())[0]))
    rotated = rng.sample(pool, min(len(pool), 2))
    return normalize_hashtags(BRAND_TAGS + rotated)


class ContentGenerator:
    def __init__(self, database, config: dict | None = None):
        self.database = database
        self.config = config  # utilisé par le client LLM multi-fournisseurs

    def generate(self, prompt: str | None = None, pillar: str | None = None) -> Content:
        """Génère un Contenu via les providers LLM configurés, puis HF, puis local.

        La recherche de brouillon acceptable (doublons, points incohérents) vit
        dans `_llm` via `generate_with_retry`. Le mode local n'est atteint que
        si TOUS les providers LLM configurés (avec clé) ont échoué, puis HF.
        """
        exclusions = {field: sorted(self.database.recent_values(field))[-180:] for field in ("title", "topic", "verse_reference", "cta", "decor")}
        hook_type = self._pick_hook_type()
        if ordered_providers(self.config or {}):
            last_exc: Exception | None = None
            try:
                return self._llm(exclusions, prompt=prompt, hook_type=hook_type, pillar=pillar)
            except Exception as exc:
                last_exc = exc
            # Tous les providers LLM (avec clé) ont échoué : repli Hugging Face.
            try:
                return self._huggingface(exclusions, avoid=str(last_exc) if last_exc else None, prompt=prompt, hook_type=hook_type, pillar=pillar)
            except Exception as hf_exc:
                last_exc = hf_exc
            # Dernier recours : générateur local déterministe (tests/reprise quota).
            return self._local(exclusions, warning=str(last_exc), hook_type=hook_type, pillar=pillar)
        # Pas de provider LLM configuré : Hugging Face d'abord, local si HF échoue.
        try:
            return self._huggingface(exclusions, prompt=prompt, hook_type=hook_type, pillar=pillar)
        except Exception as hf_exc:
            return self._local(exclusions, warning=str(hf_exc), hook_type=hook_type, pillar=pillar)

    def _pick_hook_type(self) -> tuple[str, str]:
        """Type d'accroche imposé : on écarte les types récents pour éviter la répétition."""
        recent = self.database.recent_values("hook_type")
        pool = [(key, label) for key, label in HOOK_TYPES if key not in recent] or HOOK_TYPES
        return random.choice(pool)

    def _llm(self, exclusions: dict[str, list[str]], avoid: str | None = None, prompt: str | None = None, hook_type=None, pillar: str | None = None) -> Content:
        from .llm import generate_with_retry

        pillar = pillar or random.choice(PILLARS)
        hook_key, hook_label = hook_type or random.choice(HOOK_TYPES)
        system_prompt = prompt or SYSTEM_PROMPT

        def build_prompt(avoid: str | None = None) -> str:
            text = (
                f"{system_prompt}\nPilier obligatoire : {pillar}.\n"
                f"Type d'accroche IMPOSÉ pour le champ \"hook\" : « {hook_label} » "
                f"(clé : {hook_key}). Construis le hook selon ce type, sans jamais le nommer.\n"
                f"Éléments interdits 90 jours : {json.dumps(exclusions, ensure_ascii=False)}"
            )
            if avoid:
                text += (
                    f"\nTon brouillon précédent a été rejeté pour ce motif : {avoid}.\n"
                    "Corrige-le maintenant : choisis un AUTRE verset, une accroche du même type "
                    "mais avec une formulation différente, un autre appel à l'action, et vérifie "
                    "que le nombre annoncé dans le titre égale exactement le nombre de points. "
                    "Aucun élément interdit ci-dessus."
                )
            return text

        def normalize(data: dict) -> Content:
            data["hashtags"] = normalize_hashtags(
                data.get("hashtags"),
                fallback=_build_hashtags(data.get("pillar", pillar), data.get("topic", ""), random.Random(data.get("topic", ""))),
            )
            data["hook_type"] = hook_key
            data.setdefault("engagement_score", None)
            content = Content(**{field: data[field] for field in Content.__dataclass_fields__})
            self._validate(content, exclusions)
            return content

        data, provider_name = generate_with_retry(
            self.config,
            system_prompt,
            build_prompt,
            validate=normalize,
            do_json=True,
        )
        self._last_provider = provider_name
        return normalize(data)

    def _huggingface(self, exclusions: dict[str, list[str]], avoid: str | None = None, prompt: str | None = None, hook_type: tuple[str, str] | None = None, pillar: str | None = None) -> Content:
        """Repli IA via Hugging Face (Mistral-7B-Instruct) quand Gemini est hors ligne."""
        from .secrets import get_secret

        token = get_secret("huggingface_token")
        if not token:
            raise RuntimeError("Aucun jeton Hugging Face configuré")
        pillar = pillar or random.choice(PILLARS)
        hook_key, hook_label = hook_type or random.choice(HOOK_TYPES)
        system_prompt = prompt or SYSTEM_PROMPT
        prompt_text = (
            f"{system_prompt}\nPilier obligatoire : {pillar}.\n"
            f"Type d'accroche IMPOSÉ pour le champ \"hook\" : « {hook_label} » "
            f"(clé : {hook_key}). Construis le hook selon ce type, sans jamais le nommer.\n"
            f"Éléments interdits 90 jours : {json.dumps(exclusions, ensure_ascii=False)}"
        )
        if avoid:
            prompt_text += (
                f"\nTon brouillon précédent a été rejeté pour ce motif : {avoid}.\n"
                "Corrige-le maintenant : choisis un AUTRE verset, une accroche du même type "
                "mais avec une formulation différente, un autre appel à l'action, et vérifie "
                "que le nombre annoncé dans le titre égale exactement le nombre de points. "
                "Aucun élément interdit ci-dessus."
            )
        data = hf_generate_json(system_prompt=system_prompt, prompt_text=prompt_text, token=token)
        data["hashtags"] = normalize_hashtags(
            data.get("hashtags"),
            fallback=_build_hashtags(data.get("pillar", pillar), data.get("topic", ""), random.Random(data.get("topic", ""))),
        )
        data["hook_type"] = hook_key
        data.setdefault("engagement_score", None)
        content = Content(**{field: data[field] for field in Content.__dataclass_fields__})
        self._validate(content, exclusions)
        return content

    def _local(self, exclusions: dict[str, list[str]], warning: str | None = None, hook_type: tuple[str, str] | None = None, pillar: str | None = None) -> Content:
        """Deterministic no-API fallback intended for setup, tests and quota recovery."""
        index = len(exclusions["title"]) + 1
        last_error = warning or "générateur local"
        for _ in range(200):
            try:
                content = self._build_local(index, hook_type=hook_type, pillar=pillar)
                self._validate(content, exclusions)
                return content
            except ValueError as exc:
                last_error = str(exc)
                index += 1
        raise ValueError(f"Impossible de générer un contenu unique après 200 essais : {last_error}")

    def _build_local(self, index: int, hook_type: tuple[str, str] | None = None, pillar: str | None = None) -> Content:
        pillar = pillar or PILLARS[index % len(PILLARS)]
        focuses = LOCAL_FOCUSES.get(pillar, LOCAL_FOCUSES["Dignité"])
        bank = LOCAL_BANK.get(pillar, next(iter(LOCAL_BANK.values())))
        # Mélange multiplicatif : chaque index donne une combinaison (focus, angle)
        # différente et bien répartie sur tout l'espace, pour que la recherche d'un
        # titre inédit ne tourne pas en rond sur des combos corrélés.
        mix = (index * 31 + 7) % (1 << 30)
        focus = focuses[mix % len(focuses)]
        angles = LOCAL_ANGLES.get(pillar, LOCAL_ANGLES["Dignité"])
        angle = angles[(mix >> 3) % len(angles)]
        topic = f"{pillar} — {focus} — {index}"
        # UN SEUL nombre pilote à la fois le titre et le nombre de points : jamais
        # deux sources indépendantes (le contrôle _validate le vérifie aussi).
        count = min(3 + index % 5, len(bank))  # 3..7 points, dans la limite éditoriale
        # ÉCHANTILLONNAGE déterministe (au lieu d'un segment contigu bank[a:b]) :
        # deux posts voisins (même jour 8h/16h, ou même semaine) partageaient
        # presque tous les points → commentaires quasi identiques. sample(index)
        # choisit des points épars, différents à chaque index, sans répétition.
        points = [
            {"heading": heading, "body": body, "application": application}
            for heading, body, application in random.Random(index).sample(bank, count)
        ]
        # Titre VARIÉ : plusieurs formulations plutôt que « N clés pour » fixe,
        # pour que deux posts voisins (même jour, même pilier) ne se ressemblent pas.
        count_label = random.Random(index).choice([
            "clés", "pratiques", "principes", "étapes", "secrets", "manières",
        ])
        title = f"{count} {count_label} pour {focus}, {angle}"
        hook_key, hook_label = hook_type or ("question_pain", "Une question qui fait mal")
        hooks = {
            "question_pain": f"Tu travailles dur pour {focus}, et pourtant tu as encore l'impression de ne pas avancer ?",
            "constat_cache": f"Beaucoup prient pour {focus}, mais ont peur en secret d'y croire vraiment.",
            "contre_intuitif": f"Ce n'est pas ton manque de moyens qui te bloque sur {focus} : c'est ce que tu crois sur toi-même.",
            "identification": f"Si tu as déjà eu honte de ton retard sur {focus}, ce post est pour toi.",
            "chiffre": f"Des milliers de personnes abandonnent chaque année sur {focus} à cause d'une seule croyance limitante.",
        }
        truths = LOCAL_TRUTHS.get(pillar, LOCAL_TRUTHS["Dignité"])
        truth = truths[index % len(truths)]
        ctas = LOCAL_CTAS.get(pillar, LOCAL_CTAS["Dignité"])
        cta = ctas[(index // len(truths)) % len(ctas)].replace("{focus}", focus)
        return Content(
            pillar=pillar, title=title, hook=hooks.get(hook_key, hooks["question_pain"]),
            topic=topic, verse_reference=f"Proverbes {(index % 31) + 1}:{(index // 31) + 1}",
            decor=["bureau élégant baigné de lumière dorée", "bibliothèque bleu marine et or", "montagnes majestueuses au lever du jour", "salon chaleureux en fin de journée", "bord de mer paisible au crépuscule"][index % 5] + f", composition {index}",
            image_prompt="Scène éditoriale premium bleu marine et or, lumière naturelle, aucun texte, aucune marque.",
            points=points,
            truth=truth,
            cta=cta,
            hashtags=_build_hashtags(pillar, topic, random.Random(topic)),
            hook_type=hook_key,
        )

    def _score_engagement(self, content: Content) -> int | None:
        """Note d'engagement (1-10) du brouillon, via un court appel LLM.

        Appelée uniquement si le service autorise le scoring (config
        `engagement_score`) sinon le quota gratuit des providers (ex. 20
        requêtes/jour sur Gemini) serait dépassé par les posts automatiques.
        Ne lève JAMAIS : un échec renvoie None et la publication continue.
        """
        if not ordered_providers(self.config or {}):
            return None
        try:
            prompt = (
                "Tu es un rédacteur social. Note de 1 à 10 (un entier seul, "
                "rien d'autre) la capacité d'engagement de ce post Facebook "
                "chrétien : accroche qui touche une douleur réelle, rythme "
                "oral court, appel à l'action précis et actionnable, pas de "
                "tournures robots, hashtags corrects.\n"
                f"TITRE : {content.title}\n"
                f"ACCROCHE : {content.hook}\n"
                f"CTA : {content.cta}\n"
                f"HASHTAGS : {' '.join(content.hashtags)}"
            )
            raw, _provider = generate_with_fallback(
                self.config or {},
                "Réponds EXCLUSIVEMENT par un entier unique (1 à 10).",
                prompt,
                do_json=False,
                max_tokens=8,
            )
            score = int(str(raw).strip()[:2])
            return score if 1 <= score <= 10 else None
        except Exception:
            return None

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
        if exclusions.get("title") and _too_close(content.title, set(exclusions["title"])):
            raise ValueError("Titre trop proche d'un post publié récemment")
