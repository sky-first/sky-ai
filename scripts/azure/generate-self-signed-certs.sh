#!/bin/bash
# DEVOPS: Gera certificados SSL auto-assinados para POC
# NOTA: Para produção, use Let's Encrypt ou certificados válidos
# Este script é apenas para habilitar HTTPS em ambiente de POC/teste

set -eu

PROJECT_DIR="${1:-$(pwd)}"
CERTS_DIR="${PROJECT_DIR}/certs"
DOMAIN="${2:-localhost}"

echo "=========================================="
echo "🔐 Gerando Certificados SSL Auto-assinados"
echo "=========================================="
echo ""

# Criar diretório de certificados
mkdir -p "$CERTS_DIR"

# Verificar se já existem certificados
if [ -f "$CERTS_DIR/fullchain.pem" ] && [ -f "$CERTS_DIR/privkey.pem" ]; then
    echo "[WARNING] Certificados já existem em $CERTS_DIR"
    read -p "Deseja regenerar? (s/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Ss]$ ]]; then
        echo "[OK] Mantendo certificados existentes"
        exit 0
    fi
    echo "🔄 Regenerando certificados..."
fi

# Gerar certificado auto-assinado válido por 365 dias
echo "Gerando certificado para domínio/IP: $DOMAIN"
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout "$CERTS_DIR/privkey.pem" \
    -out "$CERTS_DIR/fullchain.pem" \
    -subj "/C=BR/ST=State/L=City/O=Organization/CN=$DOMAIN" \
    -addext "subjectAltName=IP:127.0.0.1,IP:$DOMAIN,DNS:localhost,DNS:$DOMAIN" 2>/dev/null || \
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout "$CERTS_DIR/privkey.pem" \
    -out "$CERTS_DIR/fullchain.pem" \
    -subj "/C=BR/ST=State/L=City/O=Organization/CN=$DOMAIN"

# Criar fullchain.pem (mesmo que cert.pem para auto-assinado)
if [ ! -f "$CERTS_DIR/fullchain.pem" ]; then
    echo "[ERROR] ERRO: Falha ao gerar certificados"
    exit 1
fi

# Ajustar permissões
chmod 600 "$CERTS_DIR/privkey.pem"
chmod 644 "$CERTS_DIR/fullchain.pem"

echo ""
echo "[OK] Certificados gerados com sucesso!"
echo "   - Certificado: $CERTS_DIR/fullchain.pem"
echo "   - Chave privada: $CERTS_DIR/privkey.pem"
echo ""
echo "[WARNING] NOTA: Certificados auto-assinados gerarão aviso no navegador."
echo "   Para produção, use Let's Encrypt ou certificados válidos."
echo ""
echo "=========================================="
echo "[OK] Certificados SSL Prontos"
echo "=========================================="

