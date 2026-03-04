# Dry-run container image: Azure CLI + Terraform
# Uso (exemplo):
#   docker build -t terraform-azurecli:1.9.0 --build-arg TERRAFORM_VERSION=1.9.0 docker/terraform-azurecli
#   docker run --rm -v "$PWD:/workspace" -w /workspace/infra/azure terraform-azurecli:1.9.0 terraform version

FROM mcr.microsoft.com/azure-cli:2.80.0

ARG TERRAFORM_VERSION=1.9.0

# Pacotes utilitários para baixar e descompactar o Terraform
RUN set -euo pipefail; \
  if command -v tdnf >/dev/null 2>&1; then \
  tdnf -y install curl unzip ca-certificates && tdnf -y clean all; \
  elif command -v apt-get >/dev/null 2>&1; then \
  apt-get update -y && apt-get install -y --no-install-recommends curl unzip ca-certificates && rm -rf /var/lib/apt/lists/*; \
  elif command -v apk >/dev/null 2>&1; then \
  apk add --no-cache curl unzip ca-certificates; \
  else \
  echo "Gerenciador de pacotes não suportado no base image" && exit 1; \
  fi

RUN set -euo pipefail; \
  arch="$(uname -m)"; \
  case "$arch" in \
  x86_64|amd64) tf_arch="amd64" ;; \
  aarch64|arm64) tf_arch="arm64" ;; \
  *) echo "Arquitetura não suportada: $arch" && exit 1 ;; \
  esac; \
  curl -fsSLo /tmp/terraform.zip "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${tf_arch}.zip"; \
  unzip -q /tmp/terraform.zip -d /usr/local/bin; \
  rm -f /tmp/terraform.zip; \
  terraform -version

WORKDIR /workspace

# Faz o container executar terraform por padrão (a Azure CLI segue disponível no PATH para o provider azurerm).
# Criar e configurar usuário não-root
RUN useradd -m -u 10001 tfuser \
  && chown -R tfuser:tfuser /workspace

USER tfuser

ENTRYPOINT ["terraform"]
