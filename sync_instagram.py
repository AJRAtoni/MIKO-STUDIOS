#!/usr/bin/env python3
"""Cache Miko's latest nine posts using the official Instagram Login API."""
import io
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from datetime import datetime
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from PIL import Image
import requests

ROOT = Path(__file__).resolve().parent
PROFILE = "mikostudios.co"
API_VERSION = "v26.0"
MAX_POSTS = 9
DAY = 86400
logger = logging.getLogger(__name__)


class SyncError(Exception):
    """A safe, actionable error that contains no access tokens or signed URLs."""


def session():
    # Scheduled runs provide retries without urllib3 logging credential-bearing URLs.
    return requests.Session()


def publication_date(post):
    value = post["timestamp"].replace("Z", "+00:00")
    value = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value)
    date = datetime.fromisoformat(value)
    if date.tzinfo is None:
        raise ValueError("Missing timezone")
    return date


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text() == content:
        return False
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
    return True


class Instagram:
    def __init__(self, client):
        self.client = client

    def get(self, route, token, **params):
        # Never log requests exceptions: refresh URLs contain credentials.
        try:
            response = self.client.get(
                f"https://graph.instagram.com/{route}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=(10, 45),
                allow_redirects=False,
            )
            data = response.json()
        except (requests.RequestException, ValueError):
            raise SyncError("Instagram no respondió correctamente; se conserva la galería.") from None
        if not isinstance(data, dict):
            raise SyncError("Instagram devolvió una respuesta no válida.")
        if response.status_code != 200 or "error" in data:
            code = data.get("error", {}).get("code", "unknown") if isinstance(data, dict) else "unknown"
            raise SyncError(f"Instagram rechazó la consulta (HTTP {response.status_code}, código {code}). Revisar acceso y permisos.")
        return data

    def account(self, token):
        result = self.get(f"{API_VERSION}/me", token, fields="user_id,username")
        account = result.get("data", [result])
        account = account[0] if isinstance(account, list) and account else account
        if not isinstance(account, dict) or account.get("username", "").lower() != PROFILE:
            raise SyncError(f"El acceso no corresponde a @{PROFILE}; no se modifica la galería.")
        user_id = str(account.get("user_id", account.get("id", "")))
        if not user_id.isdigit():
            raise SyncError("Instagram no devolvió un identificador válido para Miko.")
        return user_id

    def refresh(self, token):
        result = self.get("refresh_access_token", token, grant_type="ig_refresh_token", access_token=token)
        if not result.get("access_token") or not isinstance(result.get("expires_in"), int) or result["expires_in"] <= DAY:
            raise SyncError("Instagram no devolvió una renovación válida.")
        return result

    def posts(self, token, user_id):
        fields = "id,media_type,media_url,thumbnail_url,permalink,timestamp,children{media_type,media_url,thumbnail_url}"
        media, after = {}, None
        # Read all pages so pinned items or API ordering cannot hide newer posts.
        for _ in range(20):
            params = {"fields": fields, "limit": 100}
            if after:
                params["after"] = after
            result = self.get(f"{API_VERSION}/{user_id}/media", token, **params)
            items = result.get("data")
            if not isinstance(items, list):
                raise SyncError("La respuesta de publicaciones no es válida.")
            for item in items:
                if not isinstance(item, dict) or not item.get("id") or not item.get("timestamp"):
                    raise SyncError("Una publicación no contiene identificador y fecha válidos.")
                media[item["id"]] = item
            paging = result.get("paging", {})
            if not paging.get("next"):
                break
            next_cursor = paging.get("cursors", {}).get("after")
            if not next_cursor or next_cursor == after:
                raise SyncError("Instagram no permite continuar la paginación de forma fiable.")
            after = next_cursor
        else:
            raise SyncError("Se alcanzó el límite de paginación; no se publica una selección incompleta.")
        if not media:
            raise SyncError("Instagram devolvió una galería vacía; se conserva la anterior.")
        try:
            return sorted(media.values(), key=publication_date, reverse=True)[:MAX_POSTS]
        except (ValueError, TypeError):
            raise SyncError("Instagram devolvió fechas incompatibles; se conserva la galería.") from None


def credentials(root, api, env):
    """Persist refreshed tokens as authenticated ciphertext, never public plaintext."""
    key = env.get("INSTAGRAM_TOKEN_KEY", "").strip()
    try:
        cipher = Fernet(key.encode())
    except (ValueError, TypeError):
        raise SyncError("Falta un secreto INSTAGRAM_TOKEN_KEY válido.") from None
    path = root / ".github/instagram-token.json"
    now = int(time.time())
    if path.exists():
        try:
            state = json.loads(path.read_text())
            if state["version"] != 1 or state["username"] != PROFILE:
                raise ValueError()
            token = cipher.decrypt(state["token"].encode()).decode()
            refresh_at = int(state["refresh_at"])
        except (InvalidToken, ValueError, KeyError, TypeError):
            raise SyncError("No se puede abrir el acceso cifrado. Revisar INSTAGRAM_TOKEN_KEY; no se reemplaza automáticamente.") from None
    else:
        token = env.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
        if not token:
            raise SyncError("Falta INSTAGRAM_ACCESS_TOKEN para la primera conexión.")
        # Bootstrap must use a freshly generated, long-lived App Dashboard token.
        # Meta only refreshes tokens older than 24 hours.
        state = {"version": 1, "username": PROFILE, "token": cipher.encrypt(token.encode()).decode(), "refresh_at": now + DAY + 3600}
        refresh_at = state["refresh_at"]
    user_id = api.account(token)
    if now >= refresh_at:
        result = api.refresh(token)
        token = result["access_token"]
        state.update(token=cipher.encrypt(token.encode()).decode(),
                     refresh_at=now + min(30 * DAY, result["expires_in"] // 2),
                     expires_at=now + result["expires_in"])
    # Save a rotated token even if subsequent media retrieval fails.
    # CI commits this encrypted file even when the sync step fails.
    atomic_json(path, state)
    return token, user_id


def permalink(value):
    url = urlparse(value or "")
    match = re.fullmatch(r"/(?:mikostudios\.co/)?(p|reel)/([A-Za-z0-9_-]+)/?", url.path)
    if url.scheme != "https" or url.hostname not in {"instagram.com", "www.instagram.com"} or not match:
        raise SyncError("Instagram devolvió un enlace de publicación no válido.")
    kind, code = match.groups()
    return f"https://www.instagram.com/{kind}/{code}/", code


def image_url(post):
    kind = post.get("media_type")
    url = post.get("thumbnail_url") if kind == "VIDEO" else post.get("media_url")
    if not url and kind == "CAROUSEL_ALBUM":
        children = post.get("children", {}).get("data", [])
        if children:
            return image_url(children[0])
    parsed = urlparse(url or "")
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not any(host == domain or host.endswith("." + domain) for domain in ("cdninstagram.com", "fbcdn.net", "fbsbx.com")):
        raise SyncError("Una publicación no tiene una imagen o miniatura disponible; se conserva la galería anterior.")
    return url


def image_extension(content):
    try:
        with Image.open(io.BytesIO(content)) as image:
            extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(image.format)
            if not extension or min(image.size) < 100 or image.width * image.height > 36_000_000:
                raise ValueError()
            image.load()
        return extension
    except (OSError, ValueError, Image.DecompressionBombError):
        raise SyncError("Una imagen está incompleta o no es válida; se conserva la galería anterior.") from None


def download(client, url):
    # This separate client has no Instagram Authorization header or cookies.
    try:
        with client.get(url, timeout=(10, 45), stream=True, allow_redirects=False) as response:
            if response.status_code != 200 or not response.headers.get("Content-Type", "").startswith("image/"):
                raise SyncError("No se pudo descargar una imagen de Instagram.")
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 20 * 1024 * 1024:
                    raise SyncError("La imagen supera el límite de descarga.")
                chunks.append(chunk)
            return b"".join(chunks)
    except requests.RequestException:
        raise SyncError("Falló una descarga; se conserva la galería anterior.") from None


def cache_feed(root, posts, image_client):
    json_path = root / "data/instagram.json"
    previous = json.loads(json_path.read_text()) if json_path.exists() else []
    existing = {post["permalink"]: post["media_url"] for post in previous}
    new_feed = []
    images = root / "data/ig_images"
    images.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="instagram-", dir=root / "data") as directory:
        staged = []
        for post in posts:
            link, code = permalink(post.get("permalink"))
            relative = existing.get(link)
            cached = root / relative if relative else None
            if cached and cached.is_file() and cached.resolve().parent == images.resolve():
                image_extension(cached.read_bytes())
            else:
                content = download(image_client, image_url(post))
                extension = image_extension(content)
                relative = f"./data/ig_images/{code}{extension}"
                temporary = Path(directory) / (code + extension)
                temporary.write_bytes(content)
                staged.append((temporary, root / relative))
            new_feed.append({"permalink": link, "media_url": relative})
        if not new_feed or len({p["permalink"] for p in new_feed}) != len(new_feed):
            raise SyncError("La selección está vacía o contiene publicaciones duplicadas.")
        # Existing images remain available until every new download is validated.
        for temporary, destination in staged:
            temporary.replace(destination)
        return atomic_json(json_path, new_feed)


def sync_instagram(root=ROOT, env=None):
    api = Instagram(session())
    token, user_id = credentials(root, api, os.environ if env is None else env)
    posts = api.posts(token, user_id)
    changed = cache_feed(root, posts, session())
    logger.info("Galería %s: %s publicaciones de @%s.", "actualizada" if changed else "sin cambios", len(posts), PROFILE)
    return changed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        sync_instagram()
    except (SyncError, OSError, ValueError) as error:
        # Do not emit arbitrary exceptions, response bodies, or signed media URLs.
        logger.error("%s", error if isinstance(error, SyncError) else "Error al leer o guardar los archivos de sincronización.")
        sys.exit(1)
