{{/*
Expand the name of the chart.
*/}}
{{- define "lumis.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "lumis.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "lumis.labels" -}}
helm.sh/chart: {{ include "lumis.name" . }}-{{ .Chart.Version | replace "+" "_" }}
{{ include "lumis.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "lumis.selectorLabels" -}}
app.kubernetes.io/name: {{ include "lumis.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Kubernetes Secret name for app credentials (created chart Secret, ExternalSecret target, or existing).
*/}}
{{- define "lumis.secretName" -}}
{{- if .Values.secrets.existingSecret }}
{{- .Values.secrets.existingSecret }}
{{- else if .Values.externalSecrets.enabled }}
{{- default "lumis-secrets" .Values.externalSecrets.targetSecretName }}
{{- else }}
{{- include "lumis.fullname" . }}-secrets
{{- end }}
{{- end }}

{{/*
Image reference with optional global registry prefix.
Usage: include "lumis.image" (dict "root" . "repository" .Values.api.image.repository "tag" .Values.api.image.tag)
*/}}
{{- define "lumis.image" -}}
{{- $root := index . "root" }}
{{- $repo := index . "repository" }}
{{- $tag := index . "tag" }}
{{- if $root.Values.global.imageRegistry }}
{{- printf "%s/%s:%s" $root.Values.global.imageRegistry $repo $tag }}
{{- else }}
{{- printf "%s:%s" $repo $tag }}
{{- end }}
{{- end }}

{{/*
Init containers: wait for Postgres/MinIO + alembic (api/worker/beat images only).
*/}}
{{- define "lumis.initContainers.dbMigrate" -}}
{{- if .Values.migrations.useInitContainer }}
{{- if .Values.postgresql.bundled.enabled }}
- name: wait-postgres
  image: busybox:1.36
  command:
    - sh
    - -c
    - until nc -z {{ include "lumis.postgresqlHost" . }} 5432; do sleep 2; done
{{- end }}
{{- if .Values.minio.bundled.enabled }}
- name: wait-minio
  image: busybox:1.36
  command:
    - sh
    - -c
    - until nc -z {{ include "lumis.minioHost" . }} 9000; do sleep 2; done
{{- end }}
- name: alembic-upgrade
  image: {{ include "lumis.image" (dict "root" . "repository" .Values.api.image.repository "tag" .Values.api.image.tag) }}
  imagePullPolicy: {{ .Values.api.image.pullPolicy }}
  command:
    - sh
    - -c
    - cd /workspace && alembic -c apps/api/alembic.ini upgrade head
  envFrom:
    - secretRef:
        name: {{ include "lumis.secretName" . }}
{{- end }}
{{- end }}

{{/*
Internal service DNS names (same namespace).
*/}}
{{- define "lumis.postgresqlHost" -}}
{{- printf "%s-postgresql" (include "lumis.fullname" .) }}
{{- end }}

{{- define "lumis.redisHost" -}}
{{- printf "%s-redis" (include "lumis.fullname" .) }}
{{- end }}

{{- define "lumis.minioHost" -}}
{{- printf "%s-minio" (include "lumis.fullname" .) }}
{{- end }}

{{/*
DATABASE_URL — asyncpg DSN for API/worker/agent.
*/}}
{{- define "lumis.databaseUrl" -}}
{{- if .Values.secrets.databaseUrl }}
{{- .Values.secrets.databaseUrl }}
{{- else if .Values.postgresql.bundled.enabled }}
{{- $u := .Values.postgresql.auth.username }}
{{- $p := .Values.postgresql.auth.password }}
{{- $db := .Values.postgresql.auth.database }}
{{- $h := include "lumis.postgresqlHost" . }}
{{- printf "postgresql+asyncpg://%s:%s@%s:5432/%s" $u $p $h $db }}
{{- else }}
{{- fail "helm: set secrets.databaseUrl or enable postgresql.bundled" }}
{{- end }}
{{- end }}

{{/*
REDIS_URL
*/}}
{{- define "lumis.redisUrl" -}}
{{- if .Values.secrets.redisUrl }}
{{- .Values.secrets.redisUrl }}
{{- else if .Values.redis.bundled.enabled }}
{{- printf "redis://%s:6379/0" (include "lumis.redisHost" .) }}
{{- else }}
{{- fail "helm: set secrets.redisUrl or enable redis.bundled" }}
{{- end }}
{{- end }}

{{/*
CELERY_BROKER_URL
*/}}
{{- define "lumis.celeryBrokerUrl" -}}
{{- if .Values.secrets.celeryBrokerUrl }}
{{- .Values.secrets.celeryBrokerUrl }}
{{- else if .Values.redis.bundled.enabled }}
{{- printf "redis://%s:6379/0" (include "lumis.redisHost" .) }}
{{- else }}
{{- fail "helm: set secrets.celeryBrokerUrl or enable redis.bundled" }}
{{- end }}
{{- end }}

{{/*
CELERY_RESULT_BACKEND
*/}}
{{- define "lumis.celeryResultBackend" -}}
{{- if .Values.secrets.celeryResultBackend }}
{{- .Values.secrets.celeryResultBackend }}
{{- else if .Values.redis.bundled.enabled }}
{{- printf "redis://%s:6379/1" (include "lumis.redisHost" .) }}
{{- else }}
{{- fail "helm: set secrets.celeryResultBackend or enable redis.bundled" }}
{{- end }}
{{- end }}

{{/*
S3 / MinIO endpoint (HTTP inside cluster).
*/}}
{{- define "lumis.s3EndpointUrl" -}}
{{- if .Values.config.s3EndpointUrl }}
{{- .Values.config.s3EndpointUrl }}
{{- else if .Values.minio.bundled.enabled }}
{{- printf "http://%s:9000" (include "lumis.minioHost" .) }}
{{- else }}
{{- fail "helm: set config.s3EndpointUrl or enable minio.bundled" }}
{{- end }}
{{- end }}

{{/*
API_BASE_URL — external URL for callbacks (OAuth, Stripe, etc.).
*/}}
{{- define "lumis.apiBaseUrl" -}}
{{- if .Values.config.apiBaseUrl }}
{{- .Values.config.apiBaseUrl }}
{{- else if .Values.ingress.enabled }}
{{- printf "https://%s" .Values.ingress.hosts.api }}
{{- else }}
{{- printf "http://%s-api:%v" (include "lumis.fullname" .) .Values.api.service.port }}
{{- end }}
{{- end }}

{{/*
FRONTEND_URL
*/}}
{{- define "lumis.frontendUrl" -}}
{{- if .Values.config.frontendUrl }}
{{- .Values.config.frontendUrl }}
{{- else if .Values.ingress.enabled }}
{{- printf "https://%s" .Values.ingress.hosts.web }}
{{- else }}
{{- printf "http://%s-web:%v" (include "lumis.fullname" .) .Values.web.service.port }}
{{- end }}
{{- end }}
