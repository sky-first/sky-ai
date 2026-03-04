#!/bin/bash
# ==============================================================================
# Script: rotate-keyvault-secret.sh
# Descrição: Rotaciona um segredo no Azure Key Vault e força a sincronização
#            no Kubernetes usando o External Secrets Operator (ESO).
# Autor: DevOps Team (Senior Pattern)
# ==============================================================================

set -e

# Cores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

usage() {
    echo -e "${YELLOW}Uso: $0 <keyvault-name> <secret-name> <new-value> <namespace>${NC}"
    echo "Exemplo: $0 akv-sky-staging-5364fd0f database-url 'postgresql://user:pass@host:5432/db' backend"
    exit 1
}

# Validar argumentos
if [ "$#" -ne 4 ]; then
    usage
fi

KV_NAME=$1
SECRET_NAME=$2
NEW_VALUE=$3
NAMESPACE=$4

echo -e "${YELLOW}--- Iniciando Rotação de Segredo: $SECRET_NAME ---${NC}"

# 1. Atualizar no Azure Key Vault
echo -e "1. Atualizando segredo no Azure Key Vault [$KV_NAME]..."
az keyvault secret set --vault-name "$KV_NAME" --name "$SECRET_NAME" --value "$NEW_VALUE" > /dev/null

echo -e "${GREEN}[OK] Segredo atualizado no Azure.${NC}"

# 2. Forçar sincronização do External Secrets no Kubernetes
echo -e "2. Notificando External Secrets Operator no namespace [$NAMESPACE]..."

# Tentar encontrar o ExternalSecret que referencia este segredo
ES_NAME=$(kubectl get externalsecrets -n "$NAMESPACE" -o json | jq -r ".items[] | select(.spec.data[].remoteRef.key == \"$SECRET_NAME\") | .metadata.name" | head -n 1)

if [ -z "$ES_NAME" ] || [ "$ES_NAME" == "null" ]; then
    echo -e "${YELLOW}[WARNING]Não foi encontrado um recurso ExternalSecret específico para '$SECRET_NAME'.${NC}"
    echo "   Dica: O External Secrets sincronizará automaticamente conforme o intervalo definido (ex: 1h)."
else
    echo -e "   Forçando trigger no ExternalSecret: $ES_NAME"
    # Adicionando uma annotation para forçar o refresh imediato
    kubectl annotate externalsecret "$ES_NAME" -n "$NAMESPACE" "force-sync=$(date +%s)" --overwrite
    echo -e "${GREEN}[OK] Trigger de sincronização enviado.${NC}"
fi

# 3. Verificação (Opcional - Requer privilégios para ler segredos no k8s)
echo -e "3. Validando sincronização local..."
sleep 5
SYNC_STATUS=$(kubectl get externalsecret "$ES_NAME" -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "Unknown")

if [ "$SYNC_STATUS" == "True" ]; then
    echo -e "${GREEN}[OK] Sincronização concluída com sucesso!${NC}"
else
    echo -e "${YELLOW}[WARNING]O segredo foi atualizado na Azure, mas o Kubernetes ainda está processando.${NC}"
    echo "   Verifique com: kubectl describe externalsecret $ES_NAME -n $NAMESPACE"
fi

echo -e "${YELLOW}--- Fim da Operação ---${NC}"
