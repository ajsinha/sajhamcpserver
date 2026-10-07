{{/* Names */}}
{{- define "sajha.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sajha.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "sajha.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sajha.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sajha.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: server
{{- end -}}

{{- define "sajha.labels" -}}
helm.sh/chart: {{ include "sajha.chart" . }}
app.kubernetes.io/name: {{ include "sajha.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: sajha
{{- end -}}

{{- define "sajha.redisSelectorLabels" -}}
app.kubernetes.io/name: {{ include "sajha.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: redis
{{- end -}}

{{- define "sajha.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "sajha.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "sajha.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) -}}
{{- end -}}

{{- define "sajha.secretName" -}}
{{- default (printf "%s-secrets" (include "sajha.fullname" .)) .Values.secrets.existingSecret -}}
{{- end -}}

{{- define "sajha.redisSecretName" -}}
{{- default (printf "%s-redis" (include "sajha.fullname" .)) .Values.redis.existingSecret -}}
{{- end -}}

{{/* Most pods that can run at once (replicas, or the autoscaler's ceiling). */}}
{{- define "sajha.maxReplicas" -}}
{{- if .Values.autoscaling.enabled -}}{{ int .Values.autoscaling.maxReplicas }}{{- else -}}{{ int .Values.replicaCount }}{{- end -}}
{{- end -}}

{{/* "true" when more than one pod can run. */}}
{{- define "sajha.multiPod" -}}
{{- if gt (int (include "sajha.maxReplicas" .)) 1 -}}true{{- end -}}
{{- end -}}

{{/* state.backend after resolving "auto". */}}
{{- define "sajha.stateBackend" -}}
{{- $b := .Values.state.backend -}}
{{- if ne $b "auto" -}}
{{- $b -}}
{{- else if or .Values.redis.enabled .Values.state.redis.url .Values.state.redis.existingSecret -}}
redis
{{- else if or (include "sajha.multiPod" .) (gt (int .Values.workers) 1) -}}
database
{{- else -}}
memory
{{- end -}}
{{- end -}}

{{/* External origin for mcp.auth.public_url. */}}
{{- define "sajha.publicUrl" -}}
{{- if .Values.config.publicUrl -}}
{{- .Values.config.publicUrl | trimSuffix "/" -}}
{{- else if and .Values.ingress.enabled .Values.ingress.hosts -}}
{{- printf "%s://%s" (ternary "https" "http" (gt (len .Values.ingress.tls) 0)) (first .Values.ingress.hosts) -}}
{{- end -}}
{{- end -}}

{{/* host:port pairs the seed init container waits for. */}}
{{- define "sajha.waitFor" -}}
{{- $t := list -}}
{{- if and .Values.redis.enabled (eq (include "sajha.stateBackend" .) "redis") -}}
{{- $t = append $t (printf "%s-redis:6379" (include "sajha.fullname" .)) -}}
{{- end -}}
{{- if and (eq .Values.database.type "postgresql") .Values.database.postgresql.host (not .Values.database.postgresql.urlSecret) -}}
{{- $t = append $t (printf "%s:%v" .Values.database.postgresql.host .Values.database.postgresql.port) -}}
{{- end -}}
{{- join " " $t -}}
{{- end -}}

{{- define "sajha.hasRWX" -}}
{{- if has "ReadWriteMany" .accessModes -}}true{{- end -}}
{{- end -}}

{{/* Refuse combinations that would silently split state between pods. */}}
{{- define "sajha.validate" -}}
{{- $multi := include "sajha.multiPod" . -}}
{{- $state := include "sajha.stateBackend" . -}}
{{- if not (has $state (list "memory" "redis" "database")) -}}
{{- fail (printf "state.backend %q: use auto, memory, redis or database" $state) -}}
{{- end -}}
{{- if $multi -}}
{{- if ne .Values.database.type "postgresql" -}}
{{- fail "more than one pod (replicaCount > 1 or autoscaling) needs database.type: postgresql; SQLite cannot be shared between pods" -}}
{{- end -}}
{{- if eq $state "memory" -}}
{{- fail "more than one pod needs state.backend redis or database (memory keeps MCP sessions, OAuth codes and tasks in one process)" -}}
{{- end -}}
{{- if and .Values.persistence.data.enabled (not .Values.persistence.data.existingClaim) (not (include "sajha.hasRWX" .Values.persistence.data)) -}}
{{- fail "more than one pod: persistence.data needs accessModes [ReadWriteMany], an existingClaim, or enabled: false (PostgreSQL holds the shared data)" -}}
{{- end -}}
{{- if and .Values.persistence.config.enabled (not .Values.persistence.config.existingClaim) (not (include "sajha.hasRWX" .Values.persistence.config)) -}}
{{- fail "more than one pod: persistence.config needs accessModes [ReadWriteMany] or an existingClaim" -}}
{{- end -}}
{{- end -}}
{{- if eq .Values.database.type "postgresql" -}}
{{- if and (not .Values.database.postgresql.urlSecret) (not .Values.database.postgresql.host) -}}
{{- fail "database.type postgresql needs database.postgresql.host (or urlSecret)" -}}
{{- end -}}
{{- end -}}
{{- if and (eq $state "redis") (not .Values.redis.enabled) (not .Values.state.redis.url) (not .Values.state.redis.existingSecret) -}}
{{- fail "state.backend redis needs redis.enabled, state.redis.url or state.redis.existingSecret" -}}
{{- end -}}
{{- if .Values.sajhanet.enabled -}}
{{- $seen := dict -}}
{{- range .Values.sajhanet.nets -}}
{{- if hasKey $seen .name -}}
{{- fail (printf "sajhanet.nets: the net %s is listed twice" .name) -}}
{{- end -}}
{{- $_ := set $seen .name true -}}
{{- if and (not .founder) (not .seeds) -}}
{{- fail (printf "sajhanet.nets %s: seeds are required unless founder: true" .name) -}}
{{- end -}}
{{- if and $multi (or (not .instanceName) (not .advertiseAddress)) -}}
{{- fail (printf "sajhanet.nets %s: more than one pod needs instanceName and advertiseAddress (every pod is the same instance; an address name would differ per pod)" .name) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* The sajhanet section of the configuration, from .Values.sajhanet (secret references
     point at the mounted Secrets; settings are passed through). */}}
{{- define "sajha.sajhanetConfig" -}}
{{- $nets := list -}}
{{- range .Values.sajhanet.nets -}}
{{- $n := dict "name" .name -}}
{{- with .instanceName }}{{- $_ := set $n "instance_name" . -}}{{- end -}}
{{- with .advertiseAddress }}{{- $_ := set $n "advertise_address" . -}}{{- end -}}
{{- if .founder }}{{- $_ := set $n "founder" true -}}{{- end -}}
{{- with .seeds }}{{- $_ := set $n "seeds" . -}}{{- end -}}
{{- if .identitySecret -}}
{{- $dir := printf "/etc/sajhanet/%s" .name -}}
{{- $id := dict "cert_ref" (printf "file:%s/instance.crt" $dir) "key_ref" (printf "file:%s/instance.key" $dir) "ca_ref" (printf "file:%s/ca.pem" $dir) -}}
{{- if .revocationList }}{{- $_ := set $id "revocation_list_ref" (printf "file:%s/revoked.json" $dir) -}}{{- end -}}
{{- $_ := set $n "identity" $id -}}
{{- end -}}
{{- if .caKeySecret -}}
{{- $ca := dict "enabled" true "key_ref" (printf "file:/etc/sajhanet-ca/%s/ca.key" .name) -}}
{{- with .settings }}{{- with .ca }}{{- $ca = merge $ca . -}}{{- end -}}{{- end -}}
{{- $_ := set $n "ca" $ca -}}
{{- end -}}
{{- $n = merge $n (deepCopy (.settings | default dict)) -}}
{{- $nets = append $nets $n -}}
{{- end -}}
{{- toYaml (dict "enabled" true "allowed_networks" .Values.sajhanet.allowedNetworks "nets" $nets) -}}
{{- end -}}

{{/* Container environment. */}}
{{- define "sajha.env" -}}
{{- $state := include "sajha.stateBackend" . -}}
- name: SAJHA_SERVER_HOST
  value: "0.0.0.0"
- name: SAJHA_SERVER_PORT
  value: "3002"
- name: SAJHA_LOGGING_LEVEL
  value: {{ .Values.config.logLevel | quote }}
- name: FORWARDED_ALLOW_IPS
  value: {{ .Values.config.forwardedAllowIps | quote }}
- name: SAJHA_WORKERS
  value: {{ .Values.workers | quote }}
- name: POD_NAME
  valueFrom:
    fieldRef:
      fieldPath: metadata.name
{{- with include "sajha.publicUrl" . }}
- name: SAJHA_MCP_AUTH_PUBLIC_URL
  value: {{ . | quote }}
{{- end }}
{{- /* secrets shared by every replica */}}
- name: SAJHA_JWT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ include "sajha.secretName" . }}
      key: {{ .Values.secrets.keys.jwtSecret }}
- name: SAJHA_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "sajha.secretName" . }}
      key: {{ .Values.secrets.keys.sessionSecret }}
- name: SAJHA_MCP_AUTH_BUILTIN_SIGNING_KEY_PEM
  valueFrom:
    secretKeyRef:
      name: {{ include "sajha.secretName" . }}
      key: {{ .Values.secrets.keys.oauthSigningKey }}
      optional: true
{{- /* database */}}
{{ include "sajha.dbEnv" . }}
{{- /* shared state */}}
- name: SAJHA_STATE_BACKEND
  value: {{ $state | quote }}
{{- if eq $state "redis" }}
{{- if .Values.redis.enabled }}
- name: REDIS_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "sajha.redisSecretName" . }}
      key: redis-password
- name: SAJHA_STATE_REDIS_URL
  value: {{ printf "redis://:$(REDIS_PASSWORD)@%s-redis:6379/0" (include "sajha.fullname" .) | quote }}
{{- else if .Values.state.redis.existingSecret }}
- name: SAJHA_STATE_REDIS_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.state.redis.existingSecret }}
      key: {{ .Values.state.redis.urlKey }}
{{- else }}
- name: SAJHA_STATE_REDIS_URL
  value: {{ .Values.state.redis.url | quote }}
{{- end }}
{{- end }}
{{- /* storage */}}
- name: SAJHA_STORAGE_BACKEND
  value: {{ .Values.storage.backend | quote }}
{{- if eq .Values.storage.backend "s3" }}
{{- with .Values.storage.s3 }}
- name: SAJHA_S3_BUCKET
  value: {{ .bucket | quote }}
- name: SAJHA_S3_PREFIX
  value: {{ .prefix | quote }}
- name: SAJHA_S3_CACHE_DIR
  value: /tmp/sajha-cache
{{- if .region }}
- name: AWS_DEFAULT_REGION
  value: {{ .region | quote }}
{{- end }}
{{- if .endpointUrl }}
- name: SAJHA_S3_ENDPOINT_URL
  value: {{ .endpointUrl | quote }}
{{- end }}
{{- end }}
{{- else if eq .Values.storage.backend "azure" }}
{{- with .Values.storage.azure }}
- name: SAJHA_AZURE_CONTAINER
  value: {{ .container | quote }}
- name: SAJHA_AZURE_PREFIX
  value: {{ .prefix | quote }}
- name: SAJHA_AZURE_CACHE_DIR
  value: /tmp/sajha-cache
{{- if .accountUrl }}
- name: SAJHA_AZURE_ACCOUNT_URL
  value: {{ .accountUrl | quote }}
{{- end }}
{{- end }}
{{- else if eq .Values.storage.backend "gcs" }}
{{- with .Values.storage.gcs }}
- name: SAJHA_GCS_BUCKET
  value: {{ .bucket | quote }}
- name: SAJHA_GCS_PREFIX
  value: {{ .prefix | quote }}
- name: SAJHA_GCS_CACHE_DIR
  value: /tmp/sajha-cache
{{- if .project }}
- name: GOOGLE_CLOUD_PROJECT
  value: {{ .project | quote }}
{{- end }}
{{- end }}
{{- end }}
{{- /* features */}}
- name: SAJHA_SANDBOX_DEFAULT_BACKEND
  value: {{ .Values.sandbox.backend | quote }}
- name: SAJHA_PLAYGROUND_ASSETS
  value: {{ .Values.playground.assets | quote }}
- name: SAJHA_OBSERVABILITY_METRICS_ENABLED
  value: {{ .Values.metrics.enabled | quote }}
- name: SAJHA_OBSERVABILITY_METRICS_AUTH
  value: {{ .Values.metrics.auth | quote }}
{{- if le (int .Values.workers) 1 }}
{{- /* one process per pod: every pod is scraped, so a pod must not re-serve the others' snapshots */}}
- name: SAJHA_OBSERVABILITY_METRICS_MULTIWORKER
  value: "off"
{{- end }}
- name: SAJHA_OBSERVABILITY_METRICS_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "sajha.secretName" . }}
      key: {{ .Values.secrets.keys.metricsToken }}
      optional: true
{{- range $k, $v := .Values.config.env }}
- name: {{ $k }}
  value: {{ $v | toString | quote }}
{{- end }}
{{- with .Values.config.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/* Database environment of the server. */}}
{{- define "sajha.dbEnv" -}}
- name: SAJHA_DB_TYPE
  value: {{ .Values.database.type | quote }}
{{- if eq .Values.database.type "postgresql" }}
{{- with .Values.database.postgresql }}
- name: SAJHA_DB_SCHEMA_CHECK
  value: {{ .schemaCheck | default "strict" | quote }}
{{- if .urlSecret }}
- name: SAJHA_DB_URL
  valueFrom:
    secretKeyRef:
      name: {{ .urlSecret }}
      key: {{ .urlKey }}
{{- else }}
- name: SAJHA_DB_HOST
  value: {{ .host | quote }}
- name: SAJHA_DB_PORT
  value: {{ .port | quote }}
- name: SAJHA_DB_NAME
  value: {{ .name | quote }}
- name: SAJHA_DB_USER
  value: {{ .user | quote }}
{{- if .existingSecret }}
- name: SAJHA_DB_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .existingSecret }}
      key: {{ .passwordKey }}
{{- end }}
{{- end }}
{{- end }}
{{- else }}
- name: SAJHA_DB_PATH
  value: /app/data/sajha.db
{{- end }}
{{- end -}}
