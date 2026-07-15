{{- define "shibahama.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- define "shibahama.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "shibahama.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- define "shibahama.labels" -}}
app.kubernetes.io/name: {{ include "shibahama.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end }}
{{- define "shibahama.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}{{ default (include "shibahama.fullname" .) .Values.serviceAccount.name }}{{ else }}{{ required "serviceAccount.name is required when serviceAccount.create=false" .Values.serviceAccount.name }}{{ end }}
{{- end }}
