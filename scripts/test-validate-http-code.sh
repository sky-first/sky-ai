#!/bin/bash
# Script de teste para validar a função validate_http_code
# Testa diferentes cenários de códigos HTTP

set -e

# Função atual (com bug)
validate_http_code_old() {
    local code="$1"
    local clean_code=$(echo "$code" | tr -d ' ' | grep -E '^[0-9]{3}$' || echo "000")
    
    if [ "$clean_code" = "000" ] || [ -z "$clean_code" ]; then
        return 1
    fi
    
    if [ "$clean_code" -ge 100 ] && [ "$clean_code" -le 599 ] 2>/dev/null; then
        echo "$clean_code"
        return 0
    fi
    
    return 1
}

# Função CORRIGIDA
validate_http_code_new() {
    local code="$1"
    
    # Remove TODOS os caracteres não numéricos e pega apenas os primeiros 3 dígitos
    local clean_code=$(echo "$code" | grep -oE '[0-9]{3}' | head -1 || echo "")
    
    # Se não encontrou exatamente 3 dígitos, é inválido
    if [ -z "$clean_code" ] || [ ${#clean_code} -ne 3 ]; then
        return 1
    fi
    
    # "000" = falha de conexão/timeout (não é código HTTP válido)
    if [ "$clean_code" = "000" ]; then
        return 1
    fi
    
    # Valida se é um código HTTP válido (100-599)
    if [ "$clean_code" -ge 100 ] && [ "$clean_code" -le 599 ] 2>/dev/null; then
        echo "$clean_code"
        return 0
    fi
    
    return 1
}

# Cores
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

test_code() {
    local code="$1"
    local expected_result="$2"  # "pass" ou "fail"
    local description="$3"
    
    echo -n "Testando: '$code' ($description)... "
    
    # Testa função antiga
    OLD_RESULT=""
    if validate_http_code_old "$code" >/dev/null 2>&1; then
        OLD_RESULT=$(validate_http_code_old "$code")
        OLD_STATUS="pass"
    else
        OLD_STATUS="fail"
    fi
    
    # Testa função nova
    NEW_RESULT=""
    if validate_http_code_new "$code" >/dev/null 2>&1; then
        NEW_RESULT=$(validate_http_code_new "$code")
        NEW_STATUS="pass"
    else
        NEW_STATUS="fail"
    fi
    
    # Compara resultados
    if [ "$NEW_STATUS" = "$expected_result" ]; then
        if [ "$OLD_STATUS" != "$NEW_STATUS" ]; then
            echo -e "${GREEN}[OK] CORRIGIDO${NC} (antiga: ${OLD_STATUS}${OLD_RESULT:+/$OLD_RESULT}, nova: ${NEW_STATUS}${NEW_RESULT:+/$NEW_RESULT})"
        else
            echo -e "${GREEN}[OK] OK${NC} (ambas: ${NEW_STATUS}${NEW_RESULT:+/$NEW_RESULT})"
        fi
        return 0
    else
        echo -e "${RED}[ERROR] FALHOU${NC} (esperado: $expected_result, obtido: $NEW_STATUS)"
        return 1
    fi
}

echo "=========================================="
echo "🧪 Teste da função validate_http_code"
echo "=========================================="
echo ""

ERRORS=0

# Testes que devem PASSAR (códigos HTTP válidos)
echo "Testes que devem PASSAR:"
echo "----------------------"
test_code "200" "pass" "Código HTTP válido" || ((ERRORS++))
test_code "404" "pass" "Código HTTP válido" || ((ERRORS++))
test_code "500" "pass" "Código HTTP válido" || ((ERRORS++))
test_code " 200 " "pass" "Código com espaços" || ((ERRORS++))
test_code "200OK" "pass" "Código com texto" || ((ERRORS++))
test_code "200\n" "pass" "Código com newline" || ((ERRORS++))

echo ""
echo "Testes que devem FALHAR:"
echo "----------------------"
test_code "000" "fail" "Código de falha de conexão" || ((ERRORS++))
test_code "000000" "fail" "Código de falha (PROBLEMA ATUAL)" || ((ERRORS++))
test_code "00000" "fail" "Código de falha com 5 zeros" || ((ERRORS++))
test_code "abc" "fail" "Texto inválido" || ((ERRORS++))
test_code "" "fail" "String vazia" || ((ERRORS++))
test_code "99" "fail" "Código muito curto" || ((ERRORS++))
test_code "600" "fail" "Código fora do range" || ((ERRORS++))

echo ""
echo "=========================================="
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}[OK] Todos os testes passaram!${NC}"
    exit 0
else
    echo -e "${RED}[ERROR] $ERRORS teste(s) falharam${NC}"
    exit 1
fi

