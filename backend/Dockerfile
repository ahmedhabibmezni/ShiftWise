# Image conteneur ShiftWise — API (slim).
#
# Sert :
#   - l'API FastAPI (uvicorn)
#   - Flower (UI de monitoring Celery)
#   - le Job d'init BDD (bootstrap.py — alembic upgrade + seed des rôles)
#
# Le mode est choisi par la commande passée au conteneur (cf. manifests
# OpenShift). Image multi-stage : stage 1 builde les wheels, stage 2 minimal.
#
# Découpage API / worker (G12) :
#   Cette image N'EMBARQUE PAS `libguestfs-tools` ni `linux-image-amd64`.
#   Ces paquets (~300 MB avec leurs dépendances + un noyau complet) ne sont
#   requis QUE par le pipeline de migration (stages Adapter/Migrator), qui
#   tourne dans le worker Celery et dans les Jobs populator/adapter.
#   Les emparquer dans l'image API/Flower — exposée publiquement via Route —
#   gonflait la surface d'attaque (un noyau + des outils de manipulation
#   d'image disque dans un pod front) sans aucun usage.
#   Le worker utilise `Dockerfile.worker`, qui PART de cette image API et y
#   ajoute la seule couche guest-tooling. Conséquence :
#     - les couches communes (base, wheels, code app) sont partagées et
#       mises en cache une seule fois ;
#     - l'image API reste minces ;
#     - le code applicatif est strictement identique entre les deux images.
#   Manifests : backend / flower / db-init référencent l'image API ;
#   celery-worker référence l'image worker (cf. commentaires des manifests).
#
# Build local :
#   docker build -t quay.io/shiftwise/backend-api:latest -f Dockerfile .
#   docker push quay.io/shiftwise/backend-api:latest
#
# Base image pinning (G10) :
#   La base DOIT être épinglée par digest @sha256: en production — un tag
#   mutable comme `python:3.11-slim` peut être ré-poussé, ce qui rend le build
#   non-reproductible et ouvre une fenêtre de supply-chain.
#
#   La base est exposée via l'ARG PYTHON_BASE, utilisé par LES DEUX stages
#   (builder + runtime) pour qu'ils restent identiques. La valeur par défaut
#   est le tag — le build fonctionne sans paramètre — mais tout build
#   production / CI DOIT passer le digest résolu :
#       docker pull python:3.11-slim
#       docker inspect --format='{{index .RepoDigests 0}}' python:3.11-slim
#       docker build --build-arg \
#         PYTHON_BASE=python:3.11-slim@sha256:<DIGEST> -f Dockerfile .
#   (le pipeline CI doit fournir ce digest via une variable de dépôt).
#   NOTE : le digest n'est pas codé en dur ici car il dépend du registre et
#   doit être résolu sur une image réellement tirée — pas inventé.
ARG PYTHON_BASE=python:3.11-slim
# tag de référence : python:3.11-slim (à figer par @sha256:<DIGEST> en prod)

# ----- Stage 1 : build wheels --------------------------------------------------
FROM ${PYTHON_BASE} AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=5

# Build deps :
#   - build-essential, pkg-config : compilation des extensions C
#   - libpq-dev    : psycopg2-binary
#   - libvirt-dev  : libvirt-python (KVM connector)
#   - libxml2-dev, libcurl4-openssl-dev : ovirt-engine-sdk-python (C extension)
#   - libffi-dev, libssl-dev : cryptography / paramiko
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config \
        libpq-dev libvirt-dev libxml2-dev libcurl4-openssl-dev \
        libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir=/wheels -r requirements.txt

# ----- Stage 2 : runtime -------------------------------------------------------
FROM ${PYTHON_BASE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Runtime deps (API — slim, cf. G12) :
#   - libpq5    : psycopg2-binary
#   - libvirt0  : libvirt-python (chargée à l'exécution — import au démarrage
#                 du service discovery)
#   - libxml2, libcurl4 : ovirt-engine-sdk-python (extension C)
#   - ca-certificates, curl : healthchecks + appels HTTPS sortants
#   PAS de qemu-utils / libguestfs-tools / linux-image-amd64 ici — ce sont des
#   dépendances du pipeline de migration, ajoutées par Dockerfile.worker.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 libvirt0 libxml2 libcurl4 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Utilisateur non-root. OpenShift restricted SCC remplace l'UID par un
# UID aléatoire pris dans la plage du namespace, mais ajoute toujours le
# GID 0 (root) en groupe supplémentaire. Conséquence : tout doit être
# accessible au groupe 0, et le HOME doit être traversable par n'importe quel
# UID — d'où le chgrp 0 + chmod g+rwX + o+rX systématique.
RUN useradd --create-home --uid 1001 --gid 0 --shell /bin/bash app
WORKDIR /home/app

# On reste root pour installer les deps + copier le code, puis on chgrp/chmod
# une seule fois à la fin avant USER 1001 (chgrp exige root).
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Code applicatif — COPY explicite (G11). Pas de `COPY . .` : on ne veut
# embarquer NI le contexte de build complet (tests, .env, config/kubeconfig,
# caches __pycache__) NI un secret par accident. On copie uniquement ce dont
# le runtime a besoin.
COPY app/         ./app/
COPY alembic/     ./alembic/
COPY alembic.ini  ./alembic.ini
COPY bootstrap.py ./bootstrap.py
COPY init_db.py   ./init_db.py

# Permissions finales : owner=app, group=0 (root), mêmes droits owner/group,
# others=lecture+traversée. Couvre n'importe quel UID assigné par le SCC.
RUN chown -R 1001:0 /home/app \
    && chmod -R g=u,o+rX /home/app

USER 1001

EXPOSE 8000

# Healthcheck (G13) — interroge l'endpoint /health de l'API.
# Pertinent uniquement quand le conteneur tourne en mode API (CMD par défaut).
# Pour les modes flower / db-init, les manifests OpenShift définissent leurs
# propres probes (httpGet /healthcheck, exec, etc.) ; Kubernetes ignore de
# toute façon le HEALTHCHECK Docker au profit des probes du pod.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# Commande par défaut = API. Overridable par les Deployments.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
