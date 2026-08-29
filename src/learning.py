import sqlite3
from datetime import datetime, timedelta

def fetch_analytics_from_platforms(db_path: str):
    """
    Récupère les stats réelles depuis l'API Facebook (Graph API)
    pour les posts des 14 derniers jours.
    Met à jour post_genome avec views_24h, likes_24h, etc.
    """
    # Charger les tokens depuis Windows Credential Manager (keyring)
    try:
        import keyring
        token = keyring.get_password("voix_prosperite", "fb_access_token")
        if not token:
            from src.secrets import get_secret
            token = get_secret("facebook_page_token")
        page_id = None
        try:
            from src.config import load_config
            config = load_config()
            page_id = config.get("page_id")
        except Exception:
            pass
    except Exception:
        return

    if not token or not page_id:
        print("[LEARNING] Token ou page_id manquant")
        return

    import requests, json
    conn = sqlite3.connect(db_path)

    # Récupérer les post_ids Facebook des 14 derniers jours
    cutoff = (datetime.now() - timedelta(days=14)).isoformat()
    try:
        posts = conn.execute(
            "SELECT id, facebook_post_id FROM publications WHERE created_at > ? AND facebook_post_id IS NOT NULL",
            (cutoff,)
        ).fetchall()
    except Exception:
        posts = []

    for (post_id, fb_post_id) in posts:
        try:
            r = requests.get(
                f"https://graph.facebook.com/v25.0/{fb_post_id}",
                params={
                    "fields": "insights.metric(post_impressions,post_reactions_by_type_total,post_shares)",
                    "access_token": token
                }, timeout=10
            )
            data = r.json()
            insights = data.get("insights", {}).get("data", [])

            views = 0; likes = 0; shares = 0
            for metric in insights:
                if metric["name"] == "post_impressions":
                    views = metric["values"][-1]["value"] if metric.get("values") else 0
                if metric["name"] == "post_reactions_by_type_total":
                    v = metric["values"][-1]["value"] if metric.get("values") else {}
                    likes = sum(v.values()) if isinstance(v, dict) else 0
                if metric["name"] == "post_shares":
                    shares = metric["values"][-1]["value"] if metric.get("values") else 0

            conn.execute(
                """UPDATE post_genome SET views_24h=?, likes_24h=?, shares_24h=?
                   WHERE post_id=?""",
                (views, likes, shares, post_id)
            )
            conn.execute(
                "UPDATE publications SET views_total=?, likes_total=? WHERE id=?",
                (views, likes, post_id)
            )
        except Exception as e:
            print(f"[LEARNING] Erreur analytics post {post_id}: {e}")
    conn.commit()
    conn.close()


def update_angle_scores(db_path: str):
    """
    Met à jour strength_score de chaque angle selon les performances moyennes
    des posts qui l'ont utilisé.
    Score = 0.5*norm_views + 0.3*norm_likes + 0.2*norm_shares
    Normalisé entre 0 et 1 par rapport au maximum observé.
    """
    conn = sqlite3.connect(db_path)

    # Calculer les stats agrégées par angle
    try:
        conn.execute("""
            UPDATE viral_angles
            SET strength_score = (
                SELECT COALESCE(
                  (0.5 * AVG(CAST(pg.views_24h AS REAL)) / NULLIF(
                    (SELECT MAX(views_24h) FROM post_genome WHERE views_24h > 0), 0)
                  + 0.3 * AVG(CAST(pg.likes_24h AS REAL)) / NULLIF(
                    (SELECT MAX(likes_24h) FROM post_genome WHERE likes_24h > 0), 0)
                  + 0.2 * AVG(CAST(pg.shares_24h AS REAL)) / NULLIF(
                    (SELECT MAX(shares_24h) FROM post_genome WHERE shares_24h > 0), 0)),
                0.3)  -- score par défaut si pas encore de données
                FROM post_genome pg
                JOIN publications p ON p.id = pg.post_id
                WHERE pg.angle_type = viral_angles.angle_type
                  AND pg.pillar = viral_angles.pillar
                  AND pg.views_24h IS NOT NULL
            )
            WHERE id IN (
                SELECT DISTINCT va.id FROM viral_angles va
                JOIN post_genome pg ON pg.angle_type = va.angle_type
            )
        """)
        conn.commit()

        # Log les top angles
        tops = conn.execute(
            "SELECT pillar, angle_type, strength_score FROM viral_angles ORDER BY strength_score DESC LIMIT 5"
        ).fetchall()
        for row in tops:
            print(f"[LEARNING] Top angle : {row[0]} | {row[1]} | score={row[2]:.3f}")
    except Exception as e:
        print(f"[LEARNING] Erreur update scores: {e}")
    conn.close()


def run_learning_cycle(db_path: str):
    """Point d'entrée hebdomadaire."""
    print("[LEARNING] Début du cycle d'apprentissage...")
    fetch_analytics_from_platforms(db_path)
    update_angle_scores(db_path)
    print("[LEARNING] Cycle terminé.")
