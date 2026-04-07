#!/bin/sh
# ── Horion API Gateway entrypoint ────────────────────────────────────────────
# 1. First run : requests a Let's Encrypt certificate via HTTP-01 challenge.
# 2. Subsequent runs: reuses the existing cert (certbot skips if still valid).
# 3. Background loop: checks for renewal every 12 h; reloads nginx on success.
#
# Required env vars:
#   DOMAIN          — public domain, e.g. api.horion.pro
#   CERTBOT_EMAIL   — contact email for Let's Encrypt account
#
# Optional env vars:
#   CERTBOT_STAGING — set to "true" to use LE staging (rate-limit-safe testing)
#   RENEWAL_INTERVAL_SEC — seconds between renewal checks (default: 43200 = 12 h)
# ─────────────────────────────────────────────────────────────────────────────
set -e

: "${DOMAIN:?DOMAIN environment variable is required (e.g. api.horion.pro)}"
: "${CERTBOT_EMAIL:?CERTBOT_EMAIL environment variable is required}"

WEBROOT="/var/www/certbot"
CERT_PATH="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
RENEWAL_INTERVAL="${RENEWAL_INTERVAL_SEC:-43200}"
NGINX_CONF="/etc/nginx/conf.d/default.conf"

log() { echo "[gateway] $*"; }

# ── Generate nginx config from template ──────────────────────────────────────
# Only ${DOMAIN} is substituted; nginx's own $variables are preserved.
mkdir -p /etc/nginx/conf.d
envsubst '${DOMAIN}' < /etc/nginx/nginx.conf.template > "${NGINX_CONF}"
log "nginx config written for domain: ${DOMAIN}"

mkdir -p "${WEBROOT}"

# ── Obtain certificate if not present ────────────────────────────────────────
if [ ! -f "${CERT_PATH}" ]; then
    log "No certificate found — requesting from Let's Encrypt for ${DOMAIN} …"

    STAGING_FLAG=""
    if [ "${CERTBOT_STAGING:-false}" = "true" ]; then
        STAGING_FLAG="--staging"
        log "WARNING: using Let's Encrypt staging environment (cert will NOT be trusted by browsers)"
    fi

    # Start nginx with minimal HTTP-only config so certbot can complete the challenge
    nginx -c /etc/nginx/nginx-acme.conf
    log "nginx started in ACME bootstrap mode (port 80 only)"

    certbot certonly \
        --webroot \
        --webroot-path="${WEBROOT}" \
        --email "${CERTBOT_EMAIL}" \
        --agree-tos \
        --no-eff-email \
        --non-interactive \
        ${STAGING_FLAG} \
        -d "${DOMAIN}"

    # Stop bootstrap nginx gracefully before starting the full one
    nginx -s quit
    log "waiting for bootstrap nginx to exit …"
    sleep 3

    log "Certificate obtained: ${CERT_PATH}"
else
    log "Certificate already present — skipping request"
fi

# ── Background renewal loop ──────────────────────────────────────────────────
# certbot renew is a no-op when the cert has more than 30 days remaining.
(
    while true; do
        sleep "${RENEWAL_INTERVAL}"
        log "Running renewal check (certbot renew) …"
        if certbot renew \
            --webroot \
            --webroot-path="${WEBROOT}" \
            --quiet; then
            log "Renewal check complete — reloading nginx"
            nginx -s reload
        else
            log "Renewal check failed — nginx not reloaded"
        fi
    done
) &

# ── Start nginx with full TLS config ─────────────────────────────────────────
log "Starting nginx with TLS for ${DOMAIN}"
nginx -t
exec nginx -g "daemon off;"
