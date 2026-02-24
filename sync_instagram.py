#!/usr/bin/env python3
"""
sync_instagram.py — Miko Studios Instagram Feed Sync

Descarga los últimos 9 posts del perfil de Instagram de Miko Studios
y los cachea localmente (imágenes + JSON) para servir el feed sin
exponer tokens en el frontend.

Usa requests directos a la API web de Instagram con cookie de sesión,
evitando dependencias de scraping como instaloader que son bloqueadas
desde IPs de centros de datos.

Uso local:
    python3 sync_instagram.py

Uso en CI/CD (GitHub Actions):
    Requiere el secreto INSTAGRAM_SESSION_ID con el valor de la cookie
    "sessionid" de una sesión activa de Instagram.
"""

import os
import sys
import json
import time
import logging
import hashlib

import requests

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Constantes
PROFILE = "mikostudios.co"
MAX_POSTS = 9
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
IMG_DIR = os.path.join(DATA_DIR, "ig_images")
JSON_FILE = os.path.join(DATA_DIR, "instagram.json")
MAX_RETRIES = 3
RETRY_DELAY = 5

# Headers que simulan un navegador real
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/122.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "X-IG-App-ID": "936619743392459",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.instagram.com/",
    "Origin": "https://www.instagram.com",
}


def ensure_directories():
    """Crea los directorios necesarios si no existen."""
    os.makedirs(IMG_DIR, exist_ok=True)
    logger.info("Directorios verificados: %s", DATA_DIR)


def create_session(session_id):
    """Crea una sesión de requests con las cookies de Instagram."""
    s = requests.Session()
    s.headers.update(HEADERS)

    if session_id:
        s.cookies.set("sessionid", session_id, domain=".instagram.com")
        s.cookies.set("ds_user_id", "", domain=".instagram.com")
        logger.info("Cookie de sesión configurada.")
    else:
        logger.warning("Sin cookie de sesión. Las peticiones pueden ser limitadas.")

    return s


def get_user_id(session, username):
    """Obtiene el user ID de Instagram a partir del username."""
    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                user = data.get("data", {}).get("user", {})
                user_id = user.get("id")
                if user_id:
                    logger.info("User ID obtenido: %s", user_id)
                    return user_id, user
            elif resp.status_code == 429:
                logger.warning("Rate limited (429). Intento %d/%d.", attempt, MAX_RETRIES)
                time.sleep(RETRY_DELAY * attempt)
            else:
                logger.warning("HTTP %d en intento %d/%d.", resp.status_code, attempt, MAX_RETRIES)
                time.sleep(RETRY_DELAY)
        except requests.RequestException as e:
            logger.warning("Error en intento %d/%d: %s", attempt, MAX_RETRIES, e)
            time.sleep(RETRY_DELAY)

    return None, None


def get_posts_from_profile(user_data):
    """Extrae los posts del perfil directamente de los datos del usuario."""
    edges = (
        user_data
        .get("edge_owner_to_timeline_media", {})
        .get("edges", [])
    )

    posts = []
    for edge in edges[:MAX_POSTS]:
        node = edge.get("node", {})
        shortcode = node.get("shortcode", "")
        display_url = node.get("display_url", "")

        if shortcode and display_url:
            posts.append({
                "shortcode": shortcode,
                "display_url": display_url,
                "permalink": f"https://www.instagram.com/p/{shortcode}/",
            })

    return posts


def get_posts_via_api(session, user_id):
    """Obtiene posts usando el endpoint de la API de Instagram."""
    url = f"https://www.instagram.com/api/v1/feed/user/{user_id}/?count={MAX_POSTS}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                posts = []
                for item in items[:MAX_POSTS]:
                    shortcode = item.get("code", "")
                    # Obtener la URL de la imagen
                    candidates = (
                        item.get("image_versions2", {})
                        .get("candidates", [])
                    )
                    display_url = candidates[0]["url"] if candidates else ""

                    if shortcode and display_url:
                        posts.append({
                            "shortcode": shortcode,
                            "display_url": display_url,
                            "permalink": f"https://www.instagram.com/p/{shortcode}/",
                        })
                return posts
            elif resp.status_code == 429:
                logger.warning("Rate limited en feed API (429). Intento %d/%d.", attempt, MAX_RETRIES)
                time.sleep(RETRY_DELAY * attempt)
            else:
                logger.warning("HTTP %d en feed API, intento %d/%d.", resp.status_code, attempt, MAX_RETRIES)
                time.sleep(RETRY_DELAY)
        except requests.RequestException as e:
            logger.warning("Error en feed API, intento %d/%d: %s", attempt, MAX_RETRIES, e)
            time.sleep(RETRY_DELAY)

    return None


def download_image(session, url, filepath):
    """Descarga una imagen con reintentos."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(resp.content)
            logger.info("  Imagen descargada: %s", os.path.basename(filepath))
            return True
        except requests.RequestException as e:
            logger.warning("  Intento %d/%d fallido: %s", attempt, MAX_RETRIES, e)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    return False


def cleanup_old_images(current_shortcodes):
    """Elimina imágenes de posts que ya no están en los últimos 9."""
    if not os.path.exists(IMG_DIR):
        return
    current_files = {f"{sc}.jpg" for sc in current_shortcodes}
    for filename in os.listdir(IMG_DIR):
        if filename.endswith(".jpg") and filename not in current_files:
            os.remove(os.path.join(IMG_DIR, filename))
            logger.info("  Imagen antigua eliminada: %s", filename)


def sync_instagram():
    """Función principal de sincronización."""
    ensure_directories()

    session_id = os.environ.get("INSTAGRAM_SESSION_ID", "").strip()
    if not session_id:
        logger.error(
            "INSTAGRAM_SESSION_ID no está configurado. "
            "Configúralo como variable de entorno o secreto de GitHub."
        )
        sys.exit(1)

    session = create_session(session_id)

    logger.info("Obteniendo perfil de @%s...", PROFILE)

    # Método 1: Obtener datos del perfil (incluye los últimos posts)
    user_id, user_data = get_user_id(session, PROFILE)

    if not user_id:
        logger.error("No se pudo obtener el perfil. Verifica la cookie de sesión.")
        sys.exit(1)

    # Intentar extraer posts de los datos del perfil
    posts = get_posts_from_profile(user_data) if user_data else []

    # Método 2: Si no hay suficientes posts, usar la API de feed
    if len(posts) < MAX_POSTS:
        logger.info("Intentando API de feed para obtener más posts...")
        api_posts = get_posts_via_api(session, user_id)
        if api_posts:
            posts = api_posts

    if not posts:
        logger.error("No se obtuvieron posts. Abortando sin modificar datos existentes.")
        sys.exit(1)

    logger.info("Se encontraron %d posts.", len(posts))

    # Descargar imágenes y construir JSON
    posts_data = []
    shortcodes = []

    for i, post in enumerate(posts[:MAX_POSTS]):
        shortcode = post["shortcode"]
        img_path = os.path.join(IMG_DIR, f"{shortcode}.jpg")

        logger.info("Procesando post %d/%d: %s", i + 1, min(len(posts), MAX_POSTS), shortcode)

        if not os.path.exists(img_path):
            success = download_image(session, post["display_url"], img_path)
            if not success:
                logger.warning("  Omitiendo post %s (imagen no descargada).", shortcode)
                continue
        else:
            logger.info("  Imagen ya cacheada: %s.jpg", shortcode)

        posts_data.append({
            "permalink": post["permalink"],
            "media_url": f"./data/ig_images/{shortcode}.jpg",
        })
        shortcodes.append(shortcode)

        # Pequeña pausa entre descargas
        if i < len(posts) - 1:
            time.sleep(1)

    if not posts_data:
        logger.error("No se procesaron posts. Abortando sin modificar datos existentes.")
        sys.exit(1)

    # Limpiar imágenes antiguas
    cleanup_old_images(shortcodes)

    # Guardar JSON
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(posts_data, f, indent=2, ensure_ascii=False)

    logger.info("Sincronización completada: %d posts guardados.", len(posts_data))
    return 0


if __name__ == "__main__":
    sys.exit(sync_instagram())
