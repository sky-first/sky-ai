#!/bin/bash
set -eo pipefail

# CRÍTICO: Definir HOME (Azure Run Command executa como root e $HOME pode não estar definido)
export HOME=${HOME:-/root}

echo '=========================================='
echo '📥 Atualizando código na VM'
echo '=========================================='
echo ''

# Configurar Git para usar token (se fornecido)
if [ -n "$GITHUB_TOKEN" ]; then
  echo '🔐 Configurando autenticação Git...'
  git config --global url."https://x-access-token:${GITHUB_TOKEN}@github.com/".insteadOf "https://github.com/"
  echo '✅ Git configurado para usar token'
else
  echo '⚠️  GITHUB_TOKEN não fornecido - repositórios públicos funcionarão, privados podem falhar'
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

echo "📋 Configuração:"
echo "   Repositório: ${REPO}"
echo "   Branch: ${BRANCH}"
echo ""

# Extrair owner e name
REPO_OWNER=${REPO%%/*}
REPO_NAME=${REPO##*/}

# Verificar primeiro por sky-poc-infra (estrutura atual)
if [ -d sky-poc-infra ]; then
  echo 'Updating sky-poc-infra repository...'
  cd sky-poc-infra
  git fetch origin || { echo "❌ Erro ao fazer fetch do repositório sky-poc-infra"; exit 1; }
  git checkout "${BRANCH}" || {
    echo "❌ Erro: Branch ${BRANCH} não encontrada no repositório sky-poc-infra"
    echo "Branches disponíveis:"
    git branch -r || true
    exit 1
  }
  git pull origin "${BRANCH}" || { echo "❌ Erro ao fazer pull da branch ${BRANCH}"; exit 1; }
  cd ..
elif [ -d poc-deploy ]; then
  echo 'Updating poc-deploy repository...'
  cd poc-deploy
  git fetch origin || { echo "❌ Erro ao fazer fetch do repositório poc-deploy"; exit 1; }
  git checkout "${BRANCH}" || {
    echo "❌ Erro: Branch ${BRANCH} não encontrada no repositório remoto"
    echo "Branches disponíveis:"
    git branch -r || true
    exit 1
  }
  git pull origin "${BRANCH}" || { echo "❌ Erro ao fazer pull da branch ${BRANCH}"; exit 1; }
  cd ..
else
  echo 'Cloning sky-poc-infra repository...'
  REPO_URL="https://github.com/${REPO}.git"
  echo "Clonando sky-poc-infra (branch: ${BRANCH})..."
  git clone -b "${BRANCH}" "${REPO_URL}" sky-poc-infra || {
    echo "❌ Erro: Branch ${BRANCH} não encontrada no repositório ${REPO_URL}"
    echo "Dica: Verifique se a branch existe no repositório remoto."
    exit 1
  }
  if [ -d sky-poc-infra ]; then
    cd sky-poc-infra
    git checkout ${BRANCH} || { echo "❌ Erro ao fazer checkout da branch ${BRANCH}"; exit 1; }
    cd ..
  fi
fi

# Backend
BACKEND_REPO_URL="https://github.com/${REPO_OWNER}/sky-poc-backend.git"
if [ -d sky-poc-backend ]; then
  echo 'Updating backend repository...'
  cd sky-poc-backend
  git fetch origin || { echo "❌ Erro ao fazer fetch do repositório backend"; exit 1; }
  git checkout "${BRANCH}" || {
    echo "❌ Erro: Branch ${BRANCH} não encontrada no backend"
    echo "Branches disponíveis:"
    git branch -r || true
    echo ""
    echo "Crie a branch ${BRANCH} no repositório backend antes de fazer o deploy."
    exit 1
  }
  git pull origin "${BRANCH}" || { echo "❌ Erro ao fazer pull da branch ${BRANCH}"; exit 1; }
  cd ..
else
  echo 'Cloning backend repository...'
  echo "Clonando backend (branch: ${BRANCH})..."
  git clone -b "${BRANCH}" "${BACKEND_REPO_URL}" sky-poc-backend || {
    echo "❌ Erro: Branch ${BRANCH} não encontrada no repositório backend (${BACKEND_REPO_URL})"
    echo "Crie a branch ${BRANCH} no repositório backend antes de fazer o deploy."
    exit 1
  }
fi

if [ ! -d backend ] && [ -d sky-poc-backend ]; then
  ln -s sky-poc-backend backend 2>/dev/null || true
fi

# Frontend
FRONTEND_REPO_URL="https://github.com/${REPO_OWNER}/sky-poc-frontend.git"
if [ -d sky-poc-frontend ]; then
  echo 'Updating frontend repository...'
  cd sky-poc-frontend
  git fetch origin || { echo "❌ Erro ao fazer fetch do repositório frontend"; exit 1; }
  git checkout "${BRANCH}" || {
    echo "❌ Erro: Branch ${BRANCH} não encontrada no frontend"
    echo "Branches disponíveis:"
    git branch -r || true
    echo ""
    echo "Crie a branch ${BRANCH} no repositório frontend antes de fazer o deploy."
    exit 1
  }
  git pull origin "${BRANCH}" || { echo "❌ Erro ao fazer pull da branch ${BRANCH}"; exit 1; }
  cd ..
else
  echo 'Cloning frontend repository...'
  echo "Clonando frontend (branch: ${BRANCH})..."
  git clone -b "${BRANCH}" "${FRONTEND_REPO_URL}" sky-poc-frontend || {
    echo "❌ Erro: Branch ${BRANCH} não encontrada no repositório frontend (${FRONTEND_REPO_URL})"
    echo "Crie a branch ${BRANCH} no repositório frontend antes de fazer o deploy."
    exit 1
  }
fi

if [ ! -d frontend ] && [ -d sky-poc-frontend ]; then
  ln -s sky-poc-frontend frontend 2>/dev/null || true
fi

# IA
IA_REPO_URL="https://github.com/${REPO_OWNER}/sky-poc-ai.git"
if [ -d sky-poc-ai ]; then
  echo 'Updating IA repository...'
  cd sky-poc-ai
  git fetch origin || { echo "❌ Erro ao fazer fetch do repositório IA"; exit 1; }
  git checkout "${BRANCH}" || {
    echo "❌ Erro: Branch ${BRANCH} não encontrada no IA"
    echo "Branches disponíveis:"
    git branch -r || true
    echo ""
    echo "Crie a branch ${BRANCH} no repositório IA antes de fazer o deploy."
    exit 1
  }
  git pull origin "${BRANCH}" || { echo "❌ Erro ao fazer pull da branch ${BRANCH}"; exit 1; }
  cd ..
else
  echo 'Cloning IA repository...'
  echo "Clonando IA (branch: ${BRANCH})..."
  git clone -b "${BRANCH}" "${IA_REPO_URL}" sky-poc-ai || {
    echo "❌ Erro: Branch ${BRANCH} não encontrada no repositório IA (${IA_REPO_URL})"
    echo "Crie a branch ${BRANCH} no repositório IA antes de fazer o deploy."
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

INFRA_DIR=''
if [ -d sky-poc-infra ]; then
  INFRA_DIR='sky-poc-infra'
elif [ -d poc-deploy ]; then
  INFRA_DIR='poc-deploy'
fi

if [ -n "$INFRA_DIR" ]; then
  cd "$INFRA_DIR"
  CURRENT_DIR=$(pwd)
  if [ ! -f docker-compose.yml ]; then
    echo "❌ ERRO: docker-compose.yml não encontrado em ${CURRENT_DIR}"
    ERRORS=$((ERRORS + 1))
  else
    echo "✅ docker-compose.yml encontrado em ${CURRENT_DIR}"
  fi
  cd ..
fi

if [ ! -d sky-poc-backend ]; then
  echo '❌ ERRO: sky-poc-backend não encontrado'
  ERRORS=$((ERRORS + 1))
else
  echo '✅ sky-poc-backend encontrado'
fi

if [ ! -d sky-poc-frontend ]; then
  echo '❌ ERRO: sky-poc-frontend não encontrado'
  ERRORS=$((ERRORS + 1))
else
  echo '✅ sky-poc-frontend encontrado'
fi

if [ ! -d sky-poc-ai ]; then
  echo '⚠️  AVISO: sky-poc-ai não encontrado (pode ser opcional)'
else
  echo '✅ sky-poc-ai encontrado'
fi

echo ''
echo 'Estrutura de diretórios:'
ls -la /home/azureuser/projeto/ | head -20

echo ''
echo '🔧 Corrigindo permissões dos diretórios...'
chown -R azureuser:azureuser /home/azureuser/projeto 2>/dev/null || {
  echo "⚠️  Aviso: Não foi possível alterar proprietário de alguns arquivos - pode ser normal"
}

echo ''
echo '📋 Permissões finais:'
ls -ld /home/azureuser/projeto || true
if [ -d /home/azureuser/projeto/sky-poc-infra ]; then
  ls -ld /home/azureuser/projeto/sky-poc-infra || true
fi

FINAL_ERRORS=${ERRORS:-0}
if [ "$FINAL_ERRORS" -gt 0 ]; then
  echo ''
  echo "❌ ERRO: ${FINAL_ERRORS} problema(s) encontrado(s) - falhando"
  exit 1
fi

echo ''
echo '✅ Código atualizado com sucesso!'
