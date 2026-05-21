# ShiftWise frontend image — multi-stage build (US5).
#
# Stage 1 builds the production bundle with Vite. Stage 2 serves the
# bundle with a rootless nginx image so the Pod can run with an
# arbitrary OpenShift UID without elevated privileges.
#
# Build:
#   docker build -t docker.io/dida1609/shiftwise-frontend:<tag> -f frontend/Dockerfile frontend
#
# Run:
#   docker run -p 8080:8080 docker.io/dida1609/shiftwise-frontend:<tag>

# ---- Stage 1 — build the SPA --------------------------------------------
FROM node:20-alpine AS builder
WORKDIR /app

# Install dependencies first so the layer caches when only source changes.
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# ---- Stage 2 — serve the SPA --------------------------------------------
FROM nginxinc/nginx-unprivileged:1.27-alpine

# The unprivileged base image already listens on 8080 by default and runs
# as UID 101. Match the manifest's containerPort.
EXPOSE 8080

# Replace the default vhost with the SPA-friendly config (history mode
# fallback to index.html, gzip, sensible MIME types).
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

# OpenShift assigns an arbitrary UID per namespace; group 0 is always
# included in the supplementary GIDs so any UID can read the bundle.
USER 0
RUN chgrp -R 0 /usr/share/nginx/html /var/cache/nginx /var/log/nginx /etc/nginx/conf.d \
    && chmod -R g=u /usr/share/nginx/html /var/cache/nginx /var/log/nginx /etc/nginx/conf.d
USER 101
