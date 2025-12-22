# Templates de CI/CD e Docker para o frontend

- Estes arquivos ficam em `templates` para não afetar os workflows atuais.
- Quando o código do frontend chegar, mova-os para:
  - `Dockerfile` e `nginx.conf` na raiz (ajuste paths se o build gerar `dist` em vez de `build`).
  - `ci.yml` e `cd.yml` para `.github/workflows/`.
- No CD, configure os segredos no repositório:
  - `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`
  - `ACR_NAME`
- Ajuste nome do app/service conforme o ambiente: `frontend-app`, `rg-frontend`, etc.
# Templates de CI/CD e Docker para o frontend

- Estes arquivos ficam em `templates` para não afetar os workflows atuais.
- Quando o código do frontend chegar, mova-os para:
  - `Dockerfile` e `nginx.conf` na raiz (ajuste paths se o build gerar `dist` em vez de `build`).
  - `ci.yml` e `cd.yml` para `.github/workflows/`.
- No CD, configure os segredos no repositório:
  - `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`
  - `ACR_NAME`
- Ajuste nome do app/service conforme o ambiente: `frontend-app`, `rg-frontend`, etc.

