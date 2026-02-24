#!/usr/bin/env python3
"""
sync_instagram.py — Miko Studios Instagram Feed Sync

Descarga los últimos 9 posts del perfil de Instagram de Miko Studios
y los cachea localmente (imágenes + JSON) para servir el feed sin
exponer tokens en el frontend.

Uso:
    python3 sync_instagram.py

Entorno CI/CD (GitHub Actions):
    Se ejecuta automáticamente cada día. Instaloader accede al perfil
    público sin necesidad de login para perfiles públicos.
"""

import os
import sys
import json
import time
import logging

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
RETRY_DELAY = 10  # seconds


def ensure_directories():
    """Crea los directorios necesarios si no existen."""
    os.makedirs(IMG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    logger.info("Directorios verificados: %s", DATA_DIR)


def download_image(url, filepath):
    """Descarga una imagen con reintentos y manejo de errores."""
    import requests

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(response.content)
            logger.info("  Imagen descargada: %s", os.path.basename(filepath))
            return True
        except requests.RequestException as e:
            logger.warning(
                "  Intento %d/%d fallido para %s: %s",
                attempt,
                MAX_RETRIES,
                os.path.basename(filepath),
                e,
            )
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
            filepath = os.path.join(IMG_DIR, filename)
            os.remove(filepath)
            logger.info("  Imagen antigua eliminada: %s", filename)


def sync_instagram():
    """Función principal de sincronización."""
    try:
        import instaloader
    except ImportError:
        logger.error("instaloader no está instalado. Ejecuta: pip3 install instaloader")
        sys.exit(1)

    try:
        import requests  # noqa: F401
    except ImportError:
        logger.error("requests no está instalado. Ejecuta: pip3 install requests")
        sys.exit(1)

    ensure_directories()

    logger.info("Iniciando sincronización del perfil @%s...", PROFILE)

    # Configurar instaloader
    L = instaloader.Instaloader(
        download_comments=False,
        download_geotags=False,
        download_video_thumbnails=False,
        save_metadata=False,
        quiet=True,
    )

    try:
        profile = instaloader.Profile.from_username(L.context, PROFILE)
        logger.info("Perfil encontrado: %s (%s posts)", profile.full_name, profile.mediacount)
    except instaloader.exceptions.ProfileNotExistsException:
        logger.error("El perfil @%s no existe.", PROFILE)
        sys.exit(1)
    except instaloader.exceptions.ConnectionException as e:
        logger.error("Error de conexión con Instagram: %s", e)
        sys.exit(1)

    posts_data = []
    shortcodes = []

    for post in profile.get_posts():
        shortcode = post.shortcode
        img_path = os.path.join(IMG_DIR, f"{shortcode}.jpg")

        logger.info("Procesando post %d/%d: %s", len(posts_data) + 1, MAX_POSTS, shortcode)

        # Descargar imagen solo si no existe
        if not os.path.exists(img_path):
            success = download_image(post.url, img_path)
            if not success:
                logger.warning("  No se pudo descargar la imagen de %s, omitiendo.", shortcode)
                continue
        else:
            logger.info("  Imagen ya cacheada: %s.jpg", shortcode)

        posts_data.append(
            {
                "permalink": f"https://www.instagram.com/p/{shortcode}/",
                "media_url": f"./data/ig_images/{shortcode}.jpg",
            }
        )
        shortcodes.append(shortcode)

        if len(posts_data) >= MAX_POSTS:
            break

    if not posts_data:
        logger.error("No se obtuvieron posts. Abortando sin modificar el JSON existente.")
        sys.exit(1)

    # Limpiar imágenes antiguas
    cleanup_old_images(shortcodes)

    # Guardar JSON
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(posts_data, f, indent=2, ensure_ascii=False)

    logger.info(
        "Sincronización completada: %d posts guardados en %s",
        len(posts_data),
        JSON_FILE,
    )

    return 0


if __name__ == "__main__":
    sys.exit(sync_instagram())
