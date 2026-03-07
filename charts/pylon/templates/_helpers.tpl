{{/*
Expand the name of the chart.
*/}}
{{- define "pylon.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "pylon.fullname" -}}
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
Create chart name and version as used by the chart label.
*/}}
{{- define "pylon.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "pylon.labels" -}}
helm.sh/chart: {{ include "pylon.chart" . }}
{{ include "pylon.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "pylon.selectorLabels" -}}
app.kubernetes.io/name: {{ include "pylon.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
API selector labels
*/}}
{{- define "pylon.apiSelectorLabels" -}}
{{ include "pylon.selectorLabels" . }}
app.kubernetes.io/component: api
{{- end }}

{{/*
Worker selector labels
*/}}
{{- define "pylon.workerSelectorLabels" -}}
{{ include "pylon.selectorLabels" . }}
app.kubernetes.io/component: worker
{{- end }}

{{/*
ServiceAccount name
*/}}
{{- define "pylon.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "pylon.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Secret name
*/}}
{{- define "pylon.secretName" -}}
{{- default (include "pylon.fullname" .) .Values.secrets.existingSecret }}
{{- end }}

{{/*
PostgreSQL host
*/}}
{{- define "pylon.postgresql.host" -}}
{{- if .Values.postgresql.enabled }}
{{- printf "%s-postgresql" (include "pylon.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Redis host
*/}}
{{- define "pylon.redis.host" -}}
{{- if .Values.redis.enabled }}
{{- printf "%s-redis-master" (include "pylon.fullname" .) }}
{{- end }}
{{- end }}

{{/*
NATS URL
*/}}
{{- define "pylon.nats.url" -}}
{{- if .Values.nats.enabled }}
{{- printf "nats://%s-nats:4222" (include "pylon.fullname" .) }}
{{- end }}
{{- end }}
