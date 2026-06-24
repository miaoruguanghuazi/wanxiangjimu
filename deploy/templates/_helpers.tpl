{{/*
==============================================================================
模板辅助函数 — 万象积木 助手 Helm Chart
==============================================================================
*/}}

{{/*
返回应用名称
*/}}
{{- define "wanxiang.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
返回完全限定应用名称（包含 release 名称）
*/}}
{{- define "wanxiang.fullname" -}}
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

{{/*
返回 Chart 名称和版本
*/}}
{{- define "wanxiang.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
返回公共标签
*/}}
{{- define "wanxiang.labels" -}}
helm.sh/chart: {{ include "wanxiang.chart" . }}
{{ include "wanxiang.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: wanxiang-ai
{{- end -}}

{{/*
返回选择器标签
*/}}
{{- define "wanxiang.selectorLabels" -}}
app.kubernetes.io/name: {{ include "wanxiang.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
返回命名空间
*/}}
{{- define "wanxiang.namespace" -}}
{{- if .Values.namespace.create -}}
{{- .Values.namespace.name -}}
{{- else -}}
{{- .Release.Namespace -}}
{{- end -}}
{{- end -}}

{{/*
返回镜像全路径
参数: (root context) (imageRepository)
*/}}
{{- define "wanxiang.image" -}}
{{- $root := index . 0 -}}
{{- $repo := index . 1 -}}
{{- $tag := $root.Values.global.imageTag | default (printf "v%s" $root.Chart.AppVersion) -}}
{{- printf "%s/%s:%s" $root.Values.global.imageRegistry $repo $tag -}}
{{- end -}}

{{/*
返回 Pod 安全上下文
*/}}
{{- define "wanxiang.podSecurityContext" -}}
runAsNonRoot: {{ .Values.podSecurity.podSecurityContext.runAsNonRoot }}
runAsUser: {{ .Values.podSecurity.podSecurityContext.runAsUser }}
runAsGroup: {{ .Values.podSecurity.podSecurityContext.runAsGroup }}
fsGroup: {{ .Values.podSecurity.podSecurityContext.fsGroup }}
seccompProfile:
  type: {{ .Values.podSecurity.podSecurityContext.seccompProfile.type }}
{{- end -}}

{{/*
返回容器安全上下文
*/}}
{{- define "wanxiang.containerSecurityContext" -}}
allowPrivilegeEscalation: {{ .Values.podSecurity.containerSecurityContext.allowPrivilegeEscalation }}
readOnlyRootFilesystem: {{ .Values.podSecurity.containerSecurityContext.readOnlyRootFilesystem }}
capabilities:
  drop:
    {{- toYaml .Values.podSecurity.containerSecurityContext.capabilities.drop | nindent 4 }}
{{- end -}}

{{/*
返回镜像拉取凭证
*/}}
{{- define "wanxiang.imagePullSecrets" -}}
{{- with .Values.global.imagePullSecrets -}}
imagePullSecrets:
  {{- toYaml . | nindent 2 -}}
{{- end -}}
{{- end -}}

{{/*
返回节点亲和性（反亲和调度，避免同节点）
*/}}
{{- define "wanxiang.podAntiAffinity" -}}
podAntiAffinity:
  preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      podAffinityTerm:
        labelSelector:
          matchExpressions:
            - key: app.kubernetes.io/name
              operator: In
              values:
                - {{ include "wanxiang.name" . }}
        topologyKey: kubernetes.io/hostname
{{- end -}}

{{/*
返回资源定义（通用模板）
参数: (resources map)
*/}}
{{- define "wanxiang.resources" -}}
{{- with . -}}
resources:
  {{- toYaml . | nindent 2 -}}
{{- end -}}
{{- end -}}
