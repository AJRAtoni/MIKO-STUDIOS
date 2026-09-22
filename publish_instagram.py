#!/usr/bin/env python3
"""Request an explicit Pages build when the public gallery differs, then verify it."""
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urljoin

import requests

ROOT = Path(__file__).resolve().parent
SITE = "https://mikostudios.co/"
REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "mikostudios-dev/MIKO-STUDIOS")


def published(client, expected):
    try:
        response = client.get(SITE + "data/instagram.json", params={"verify": time.time_ns()}, timeout=20)
        response.raise_for_status()
        if response.json() != expected:
            return False
        for post in expected:
            response = client.head(urljoin(SITE, post["media_url"]), timeout=20)
            if response.status_code != 200 or not response.headers.get("Content-Type", "").startswith("image/"):
                return False
        return True
    except (requests.RequestException, ValueError):
        return False


def main(force=False):
    expected = json.loads((ROOT / "data/instagram.json").read_text())
    if not expected:
        raise RuntimeError("No se puede publicar una galería vacía.")
    with requests.Session() as public:
        if not force and published(public, expected):
            print("La galería pública ya coincide y todas las imágenes están disponibles.")
            return
        token = os.environ.get("GH_TOKEN", "")
        if not token:
            raise RuntimeError("Falta GH_TOKEN para solicitar la publicación de Pages.")
        with requests.Session() as github:
            github.headers.update(Authorization=f"Bearer {token}", Accept="application/vnd.github+json")
            response = github.post(f"https://api.github.com/repos/{REPOSITORY}/pages/builds", timeout=30)
            if response.status_code != 201:
                raise RuntimeError(f"GitHub no aceptó la publicación (HTTP {response.status_code}). Revisar el permiso pages:write y la fuente main / root.")
            # Require a completed build even when manually republishing unchanged data.
            for _ in range(30):
                time.sleep(10)
                build = github.get(f"https://api.github.com/repos/{REPOSITORY}/pages/builds/latest", timeout=30)
                build.raise_for_status()
                status = build.json().get("status")
                if status == "errored":
                    raise RuntimeError("GitHub Pages no pudo completar la publicación.")
                if status == "built" and published(public, expected):
                    print("Publicación verificada: compilación terminada, JSON e imágenes disponibles en mikostudios.co.")
                    return
        raise RuntimeError("La nueva galería aún no se verifica en público. Se reintentará en la siguiente sincronización.")


if __name__ == "__main__":
    try:
        main(force=os.environ.get("FORCE_PUBLISH") == "true")
    except (RuntimeError, OSError, ValueError, requests.RequestException) as error:
        print(str(error) if isinstance(error, RuntimeError) else "Error al publicar o verificar la galería.", file=sys.stderr)
        sys.exit(1)
