# ── Horion API Gateway image ──────────────────────────────────────────────────
# nginx:alpine + certbot for Let's Encrypt TLS termination.
FROM nginx:alpine

# Install certbot (webroot plugin is pure Python, no extra apk package needed)
RUN apk add --no-cache certbot python3 py3-pip \
 && pip3 install certbot --break-system-packages --quiet \
 && mkdir -p /var/www/certbot /etc/letsencrypt

# Copy configs and entrypoint
COPY nginx.conf.template /etc/nginx/nginx.conf.template
COPY nginx-acme.conf     /etc/nginx/nginx-acme.conf
COPY entrypoint.sh       /entrypoint.sh
RUN  chmod +x            /entrypoint.sh

EXPOSE 80 443
ENTRYPOINT ["/entrypoint.sh"]
