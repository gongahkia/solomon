{{/* SPDX-License-Identifier: Apache-2.0 */}}

{{- define "solomon.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "solomon.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := include "solomon.name" . }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "solomon.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "solomon.labels" -}}
helm.sh/chart: {{ include "solomon.chart" . }}
app.kubernetes.io/name: {{ include "solomon.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "solomon.selectorLabels" -}}
app.kubernetes.io/name: {{ include "solomon.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "solomon.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "solomon.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "solomon.image" -}}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag }}
{{- end }}

{{- define "solomon.databaseHost" -}}
{{- if .Values.postgresql.enabled }}
{{- printf "%s-postgresql" (include "solomon.fullname" .) }}
{{- else }}
{{- required "database.host is required when postgresql.enabled=false" .Values.database.host }}
{{- end }}
{{- end }}

{{- define "solomon.stateClaimName" -}}
{{- default (printf "%s-state" (include "solomon.fullname" .)) .Values.persistence.existingClaim }}
{{- end }}

{{- define "solomon.validate" -}}
{{- $_ := required "secrets.contentEncryption.existingSecret is required" .Values.secrets.contentEncryption.existingSecret }}
{{- $_ := required "secrets.contentEncryption.keyRef is required" .Values.secrets.contentEncryption.keyRef }}
{{- $_ := required "database.existingSecret is required" .Values.database.existingSecret }}
{{- if eq .Values.auth.mode "oidc" }}
{{- $_ := required "auth.oidc.issuer is required when auth.mode=oidc" .Values.auth.oidc.issuer }}
{{- $_ := required "auth.oidc.audience is required when auth.mode=oidc" .Values.auth.oidc.audience }}
{{- if not .Values.auth.oidc.roleMappings }}{{ fail "auth.oidc.roleMappings is required when auth.mode=oidc" }}{{ end }}
{{- else if eq .Values.auth.mode "legacy-api-key" }}
{{- $_ := required "auth.legacyApiKeySecret.name is required when auth.mode=legacy-api-key" .Values.auth.legacyApiKeySecret.name }}
{{- else }}
{{- fail "auth.mode must be oidc or legacy-api-key" }}
{{- end }}
{{- if .Values.observability.openTelemetry.enabled }}
{{- $_ := required "observability.openTelemetry.endpoint is required when OpenTelemetry is enabled" .Values.observability.openTelemetry.endpoint }}
{{- end }}
{{- end }}

{{- define "solomon.appEnvironment" -}}
- name: SOLOMON_SKU
  value: server
- name: SOLOMON_SERVER_AUTH_MODE
  value: {{ .Values.auth.mode | quote }}
- name: SOLOMON_CONTENT_ENCRYPTION_KEY_REF
  value: {{ .Values.secrets.contentEncryption.keyRef | quote }}
- name: SOLOMON_CONTENT_ENCRYPTION_KEY_FILE
  value: {{ printf "/run/secrets/content-encryption/%s" .Values.secrets.contentEncryption.key | quote }}
- name: SOLOMON_DATABASE_HOST
  value: {{ include "solomon.databaseHost" . | quote }}
- name: SOLOMON_DATABASE_PORT
  value: {{ .Values.database.port | quote }}
- name: SOLOMON_DATABASE_NAME
  value: {{ .Values.database.name | quote }}
- name: SOLOMON_DATABASE_USER
  value: {{ .Values.database.user | quote }}
- name: POSTGRES_PASSWORD_FILE
  value: {{ printf "/run/secrets/database/%s" .Values.database.passwordKey | quote }}
- name: SOLOMON_DATABASE_SSLMODE
  value: {{ .Values.database.sslMode | quote }}
- name: SOLOMON_DATA_DIR
  value: /var/lib/solomon/data
- name: SOLOMON_JOURNAL_DIR
  value: /var/lib/solomon/journal
- name: SOLOMON_ZERO_EGRESS_MODE
  value: "true"
- name: SOLOMON_ALLOW_REMOTE_EGRESS
  value: "false"
{{- if eq .Values.auth.mode "oidc" }}
- name: SOLOMON_OIDC_ISSUER
  value: {{ .Values.auth.oidc.issuer | quote }}
- name: SOLOMON_OIDC_AUDIENCE
  value: {{ .Values.auth.oidc.audience | quote }}
- name: SOLOMON_OIDC_ROLE_CLAIM
  value: {{ .Values.auth.oidc.roleClaim | quote }}
- name: SOLOMON_OIDC_ROLE_MAPPINGS
  value: {{ .Values.auth.oidc.roleMappings | toJson | quote }}
{{- else }}
- name: SOLOMON_SERVER_API_KEY_FILE
  value: {{ printf "/run/secrets/server-api-key/%s" .Values.auth.legacyApiKeySecret.key | quote }}
{{- end }}
{{- if .Values.observability.openTelemetry.enabled }}
- name: SOLOMON_TELEMETRY_ENABLED
  value: "true"
- name: SOLOMON_TELEMETRY_SERVICE_NAME
  value: {{ .Values.observability.openTelemetry.serviceName | quote }}
- name: SOLOMON_TELEMETRY_OTLP_ENDPOINT
  value: {{ .Values.observability.openTelemetry.endpoint | quote }}
{{- end }}
{{- end }}

{{- define "solomon.appSecretVolumes" -}}
- name: content-encryption
  secret:
    secretName: {{ .Values.secrets.contentEncryption.existingSecret }}
    defaultMode: 0400
- name: database
  secret:
    secretName: {{ .Values.database.existingSecret }}
    defaultMode: 0400
{{- if eq .Values.auth.mode "legacy-api-key" }}
- name: server-api-key
  secret:
    secretName: {{ .Values.auth.legacyApiKeySecret.name }}
    defaultMode: 0400
{{- end }}
{{- end }}

{{- define "solomon.appSecretVolumeMounts" -}}
- name: content-encryption
  mountPath: /run/secrets/content-encryption
  readOnly: true
- name: database
  mountPath: /run/secrets/database
  readOnly: true
{{- if eq .Values.auth.mode "legacy-api-key" }}
- name: server-api-key
  mountPath: /run/secrets/server-api-key
  readOnly: true
{{- end }}
{{- end }}

{{- define "solomon.appVolumes" -}}
- name: state
  persistentVolumeClaim:
    claimName: {{ include "solomon.stateClaimName" . }}
- name: tmp
  emptyDir: {}
{{ include "solomon.appSecretVolumes" . }}
{{- end }}

{{- define "solomon.appVolumeMounts" -}}
- name: state
  mountPath: /var/lib/solomon
- name: tmp
  mountPath: /tmp
{{ include "solomon.appSecretVolumeMounts" . }}
{{- end }}
