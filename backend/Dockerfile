# Image conteneur ShiftWise — sert :
#   - l'API FastAPI (uvicorn)
#   - les workers Celery
#   - Flower
#   - le Job d'init BDD (bootstrap.py)
#
# Le mode est choisi par la commande passée au conteneur (cf. manifests
# OpenShift). Image multi-stage : stage 1 builde les wheels, stage 2 minimal.
#
# Build local :
#   docker build -t quay.io/shiftwise/backend:latest -f Dockerfile .
#   docker push quay.io/shiftwise/backend:latest

# ----- Stage 1 : build wheels --------------------------------------------------
FROM python:3.11-slim AS builder

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
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Runtime deps :
#   - libpq5    : psycopg2-binary
#   - libvirt0  : libvirt-python (chargée à l'exécution)
#   - libxml2, libcurl4 : ovirt-engine-sdk-python (extension C)
#   - ca-certificates, curl : healthchecks + appels HTTPS sortants
#   - qemu-utils : binaire qemu-img utilisé par le migrator populator
#                  (qemu-img convert qcow2 -> raw, single binary ~3 MB)
#   - libguestfs-tools : virt-customize / virt-inspector pour le stage
#                        Adapter (mute le qcow2 en place pour fix réseau,
#                        console série, GRUB). ~250 MB avec deps mais
#                        permet une seule image partagée backend/worker/
#                        populator/adapter.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 libvirt0 libxml2 libcurl4 ca-certificates curl \
        qemu-utils \
        libguestfs-tools linux-image-amd64 \
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

# Code applicatif.
COPY . .

# Permissions finales : owner=app, group=0 (root), mêmes droits owner/group,
# others=lecture+traversée. Couvre n'importe quel UID assigné par le SCC.
RUN chown -R 1001:0 /home/app \
    && chmod -R g=u,o+rX /home/app

USER 1001

EXPOSE 8000

# Commande par défaut = API. Overridable par les Deployments.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
