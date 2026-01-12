#!/bin/bash
set -eo pipefail

# CRÍTICO: Definir HOME (Azure Run Command executa como root e $HOME pode não estar definido)
export HOME=${HOME:-/root}

echo '=========================================='
echo '📥 Atualizando código na VM'
echo '=========================================='
echo ''

# Configurar URL com token se fornecido
# Configurar URL com token se fornecido
if [ -n "$GITHUB_TOKEN" ]; then
  # Detectar tipo de token
  if [[ "$GITHUB_TOKEN" == "ghp_"* ]] || [[ "$GITHUB_TOKEN" == "github_pat_"* ]]; then
    # Personal Access Token (PAT): Usar token como username
    AUTH_REPO_URL="https://${GITHUB_TOKEN}@github.com"
    echo '🔐 Usando Personal Access Token (PAT) para autenticação Git'
  else
    # GitHub Action Token (GITHUB_TOKEN): Usar x-access-token como user
    AUTH_REPO_URL="https://x-access-token:${GITHUB_TOKEN}@github.com"
    echo '🔐 Usando GitHub Action/Installation Token'
  fi
else
  AUTH_REPO_URL="https://github.com"
  echo '⚠️  GITHUB_TOKEN não fornecido - usando URLs públicas'
fi

# Garantir que diretório existe (CRÍTICO)
echo ''
echo '📁 Criando/verificando diretório do projeto...'

if [ ! -d /home/azureuser/projeto ]; then
  mkdir -p /home/azureuser/projeto || { echo "❌ ERRO: Falha ao criar diretório /home/azureuser/projeto"; exit 1; }
  echo '✅ Diretório criado: /home/azureuser/projeto'
else
  echo '✅ Diretório já existe: /home/azureuser/projeto'
fi

# CRÍTICO: Corrigir proprietário e permissões do diretório
chown -R azureuser:azureuser /home/azureuser/projeto 2>/dev/null || {
  echo "⚠️  Aviso: Não foi possível alterar proprietário do diretório - pode já estar correto"
}
chmod 755 /home/azureuser/projeto 2>/dev/null || true

# Verificar permissões antes de continuar
if [ ! -w /home/azureuser/projeto ]; then
  echo "❌ ERRO: Diretório /home/azureuser/projeto não tem permissão de escrita"
  echo "Permissões atuais:"
  ls -ld /home/azureuser/projeto || true
  exit 1
fi

cd /home/azureuser/projeto || { echo "❌ ERRO: Não foi possível entrar no diretório /home/azureuser/projeto"; exit 1; }
echo '📂 Diretório atual:'
pwd
echo ''

# Corrigir erro de "dubious ownership" do Git (CRÍTICO para CI/CD na Azure)
echo '🛡️  Configurando diretórios seguros para o Git...'
# Para o root (quem geralmente executa o script via RunCommand)
git config --global --add safe.directory '*' || true
# Para o azureuser (quem é o dono dos arquivos)
sudo -u azureuser git config --global --add safe.directory '*' || true
echo ''

echo "📋 Configuração:"
echo "   Repositório: ${REPO}"
echo "   Branch: ${BRANCH}"
echo ""

# Extrair owner e name
REPO_OWNER=${REPO%%/*}
REPO_NAME=${REPO##*/}

# 1. Infra / Poc-Deploy
if [ -d sky-poc-infra ]; then
  echo 'Updating sky-poc-infra repository...'
  cd sky-poc-infra
  git remote set-url origin "${AUTH_REPO_URL}/${REPO_OWNER}/sky-poc-infra.git"
  git fetch origin || { echo "❌ Erro ao fazer fetch do repositório sky-poc-infra"; exit 1; }
  git checkout "${BRANCH}" || { echo "❌ Erro: Branch ${BRANCH} não encontrada no infra"; exit 1; }
  git reset --hard "origin/${BRANCH}" || { echo "❌ Erro ao fazer reset para a branch ${BRANCH}"; exit 1; }
  cd ..
elif [ -d poc-deploy ]; then
  echo 'Updating poc-deploy repository...'
  cd poc-deploy
  git remote set-url origin "${AUTH_REPO_URL}/${REPO_OWNER}/poc-deploy.git"
  git fetch origin || { echo "❌ Erro ao fazer fetch do repositório poc-deploy"; exit 1; }
  git checkout "${BRANCH}" || { echo "❌ Erro: Branch ${BRANCH} não encontrada no poc-deploy"; exit 1; }
  git reset --hard "origin/${BRANCH}" || { echo "❌ Erro ao fazer reset para a branch ${BRANCH}"; exit 1; }
  cd ..
else
  echo 'Cloning sky-poc-infra repository...'
  git clone -b "${BRANCH}" "${AUTH_REPO_URL}/${REPO_OWNER}/sky-poc-infra.git" sky-poc-infra || {
    echo "❌ Erro: Falha ao clonar infra."
    exit 1
  }
fi

# 2. Backend
BACKEND_REPO="${REPO_OWNER}/sky-poc-backend"
if [ -d sky-poc-backend ]; then
  echo 'Updating backend repository...'
  cd sky-poc-backend
  git remote set-url origin "${AUTH_REPO_URL}/${BACKEND_REPO}.git"
  git fetch origin || { echo "❌ Erro ao fazer fetch do repositório backend"; exit 1; }
  git checkout "${BRANCH}" || { echo "❌ Erro: Branch ${BRANCH} não encontrada no backend"; exit 1; }
  git reset --hard "origin/${BRANCH}" || { echo "❌ Erro ao fazer reset para a branch ${BRANCH}"; exit 1; }
  cd ..
else
  echo 'Cloning backend repository...'
  git clone -b "${BRANCH}" "${AUTH_REPO_URL}/${BACKEND_REPO}.git" sky-poc-backend || {
    echo "❌ Erro: Falha ao clonar backend."
    exit 1
  }
fi

if [ ! -d backend ] && [ -d sky-poc-backend ]; then
  ln -s sky-poc-backend backend 2>/dev/null || true
fi

# 3. Frontend
FRONTEND_REPO="${REPO_OWNER}/sky-poc-frontend"
if [ -d sky-poc-frontend ]; then
  echo 'Updating frontend repository...'
  cd sky-poc-frontend
  git remote set-url origin "${AUTH_REPO_URL}/${FRONTEND_REPO}.git"
  git fetch origin || { echo "❌ Erro ao fazer fetch do repositório frontend"; exit 1; }
  git checkout "${BRANCH}" || { echo "❌ Erro: Branch ${BRANCH} não encontrada no frontend"; exit 1; }
  git reset --hard "origin/${BRANCH}" || { echo "❌ Erro ao fazer reset para a branch ${BRANCH}"; exit 1; }
  cd ..
else
  echo 'Cloning frontend repository...'
  git clone -b "${BRANCH}" "${AUTH_REPO_URL}/${FRONTEND_REPO}.git" sky-poc-frontend || {
    echo "❌ Erro: Falha ao clonar frontend."
    exit 1
  }
fi

if [ ! -d frontend ] && [ -d sky-poc-frontend ]; then
  ln -s sky-poc-frontend frontend 2>/dev/null || true
fi

# 4. AI
IA_REPO="${REPO_OWNER}/sky-poc-ai"
if [ -d sky-poc-ai ]; then
  echo 'Updating AI repository...'
  cd sky-poc-ai
  git remote set-url origin "${AUTH_REPO_URL}/${IA_REPO}.git"
  git fetch origin || { echo "❌ Erro ao fazer fetch do repositório IA"; exit 1; }
  git checkout "${BRANCH}" || { echo "❌ Erro: Branch ${BRANCH} não encontrada no IA"; exit 1; }
  git reset --hard "origin/${BRANCH}" || { echo "❌ Erro ao fazer reset para a branch ${BRANCH}"; exit 1; }
  cd ..
else
  echo 'Cloning AI repository...'
  git clone -b "${BRANCH}" "${AUTH_REPO_URL}/${IA_REPO}.git" sky-poc-ai || {
    echo "❌ Erro: Falha ao clonar IA."
    exit 1
  }
fi

if [ ! -d ia ] && [ -d sky-poc-ai ]; then
  ln -s sky-poc-ai ia 2>/dev/null || true
fi

echo ''
echo '=========================================='
echo '✅ Validação Final'
echo '=========================================='

ERRORS=0

if [ ! -d sky-poc-infra ] && [ ! -d poc-deploy ]; then
  echo '❌ ERRO: sky-poc-infra ou poc-deploy não encontrado'
  ERRORS=$((ERRORS + 1))
fi

if [ ! -d sky-poc-backend ]; then
  echo '❌ ERRO: sky-poc-backend não encontrado'
  ERRORS=$((ERRORS + 1))
fi

if [ ! -d sky-poc-frontend ]; then
  echo '❌ ERRO: sky-poc-frontend não encontrado'
  ERRORS=$((ERRORS + 1))
fi

echo ''
echo 'Estrutura de diretórios:'
ls -la /home/azureuser/projeto/ | head -20

echo ''
echo '🔧 Corrigindo permissões dos diretórios...'
chown -R azureuser:azureuser /home/azureuser/projeto 2>/dev/null || true

if [ "$ERRORS" -gt 0 ]; then
  echo ''
  echo "❌ ERRO: ${ERRORS} problema(s) encontrado(s) - falhando"
  exit 1
fi

echo ''
echo '✅ Código atualizado com sucesso!'
