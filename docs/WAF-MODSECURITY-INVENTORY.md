# Inventário WAF / ModSecurity (staging)

Documento de referência para o tuning do ModSecurity no `ingress-nginx`.

## Baseline global do WAF (staging)

- Componente: `ingress-nginx` (Chart `ingress-nginx`, versão `4.8.3`)
- Arquivo IaC:
  - [`gitops/bootstrap/staging/ingress-nginx.yaml`](../gitops/bootstrap/staging/ingress-nginx.yaml)
- Configuração relevante:
  - `enable-modsecurity: "true"`
  - `enable-owasp-modsecurity-crs: "true"`
  - `modsecurity-snippet` define:
    - `SecRuleEngine DetectionOnly`

Implicação: o CRS está ligado e detecta, mas inicialmente não bloqueia (tuning/observabilidade primeiro).

## Exceções aplicadas (rule removals via Ingress annotations)

Rule(s) removida(s):

- `942100` (via `nginx.ingress.kubernetes.io/modsecurity-snippet: "SecRuleRemoveById 942100"`)

> Observação: a exceção é aplicada por objeto/endpoint de Ingress (ou seja, por host/rota), não globalmente no cluster.

### 1) App `sky-be-teamblue-stg` (TeamBlue Backend)

- Arquivo (helm values inline no Application):
  - [`gitops/bootstrap/staging/teamblue-backend.yaml`](../gitops/bootstrap/staging/teamblue-backend.yaml)
- Onde a exceção está aplicada:
  - `nginx.ingress.kubernetes.io/modsecurity-snippet: "SecRuleRemoveById 942100"`
- Hosts e paths afetados:
  - `teamblue-api.skyfirstlabs.com`
    - path: `/api(/|$)(.*)` (pathType: `ImplementationSpecific`)
  - `teamblue.skyfirstlabs.com`
    - path: `/api(/|$)(.*)` (pathType: `ImplementationSpecific`)
  - `plataform.teamblue-stg.skyfirstlabs.com`
    - path: `/api` (pathType: `Prefix`)

### 2) App `sky-fe-teamblue-stg` (TeamBlue Frontend)

- Arquivo (helm values inline no Application):
  - [`gitops/bootstrap/staging/teamblue-frontend.yaml`](../gitops/bootstrap/staging/teamblue-frontend.yaml)
- Onde a exceção está aplicada:
  - `nginx.ingress.kubernetes.io/modsecurity-snippet: "SecRuleRemoveById 942100"`
- Hosts e paths afetados:
  - `teamblue.skyfirstlabs.com`
    - path: `/` (pathType: `Prefix`)
    - path: `/api` (pathType: `Prefix`)
  - `plataform.teamblue-stg.skyfirstlabs.com`
    - path: `/` (pathType: `Prefix`)
    - path: `/api` (pathType: `Prefix`)

### 3) App `sky-be-stg` (Backend Workspace / Staging)

- Arquivo (valores do chart):
  - [`gitops/charts/common-app/values-sky-be-stg.yaml`](../gitops/charts/common-app/values-sky-be-stg.yaml)
- Onde a exceção está aplicada:
  - `nginx.ingress.kubernetes.io/modsecurity-snippet: "SecRuleRemoveById 942100"`
- Hosts e paths afetados:
  - `api-stg.skyfirstlabs.com`
    - path: `/` (pathType: `Prefix`)

### 4) App `sky-fe-stg` (Frontend Workspace / Staging)

- Arquivo (valores do chart):
  - [`gitops/charts/common-app/values-sky-fe-stg.yaml`](../gitops/charts/common-app/values-sky-fe-stg.yaml)
- Onde a exceção está aplicada:
  - `nginx.ingress.kubernetes.io/modsecurity-snippet: "SecRuleRemoveById 942100"`
- Hosts e paths afetados:
  - `workspace-stg.skyfirstlabs.com`
    - path: `/` (pathType: `Prefix`)
    - path: `/api` (pathType: `Prefix`)

## Evidência (strings exatas encontradas no repositório)

O padrão abaixo aparece nos arquivos listados:

- `nginx.ingress.kubernetes.io/modsecurity-snippet: "SecRuleRemoveById 942100"`

Arquivos onde foi encontrado:

- `gitops/bootstrap/staging/teamblue-backend.yaml`
- `gitops/bootstrap/staging/teamblue-frontend.yaml`
- `gitops/bootstrap/staging/backend.yaml` (via inline helm values, para o app workspace)
- `gitops/bootstrap/staging/frontend.yaml` (via inline helm values, para o app workspace)
- `gitops/charts/common-app/values-sky-be-stg.yaml`
- `gitops/charts/common-app/values-sky-fe-stg.yaml`
- `gitops/charts/common-app/values-sky-be-teamblue-stg.yaml`
- `gitops/charts/common-app/values-sky-fe-teamblue-stg.yaml`

## Próxima etapa sugerida

Validar se o controller do `ingress-nginx` (e logs ModSecurity) está chegando ao Loki para que a fase de calibração (DetectionOnly -> Prevention) seja baseada em dados.
