import asyncio
import edge_tts
import os

VOICE = "fr-FR-HenriNeural"  # Voix masculine francophone professionnelle
# Alternative féminine : "fr-FR-DeniseNeural"

async def generate_voice(text: str, output_path: str) -> str:
    """Génère un fichier audio MP3 depuis du texte. Retourne le chemin."""
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(output_path)
    return output_path

def text_to_speech(text: str, output_path: str) -> str:
    """Wrapper synchrone pour generate_voice."""
    asyncio.run(generate_voice(text, output_path))
    return output_path

def build_narration_text(content: dict) -> str:
    """
    Construit le texte de narration depuis le contenu généré.
    content doit avoir : hook, points (list of {heading, body, application}),
    truth, cta, verse_reference
    Retourne une narration orale naturelle, max 55 secondes de parole.
    """
    parts = []
    if content.get("hook"):
        parts.append(content["hook"])
    for point in content.get("points", [])[:3]:  # max 3 points pour tenir en 55s
        if point.get("heading"):
            parts.append(point["heading"] + ".")
        if point.get("application"):
            parts.append(point["application"])
    if content.get("truth"):
        parts.append(content["truth"])
    if content.get("cta"):
        parts.append(content["cta"])
    return " ".join(parts)
