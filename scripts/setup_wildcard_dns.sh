#!/bin/bash
# 🚀 Automação de DNS Wildcard para Sky Platform
# Este script configura o Azure DNS para aceitar qualquer subdomínio dinâmico.

RESOURCE_GROUP="rg-core-infra-prd"
DNS_ZONE="skyfirstlabs.com"
LOAD_BALANCER_IP="135.18.146.170" # IP do Ingress Controller (ingress-nginx)

echo "🛰️ Configurando DNS para os domínios reais em $DNS_ZONE..."

# Registros Flat (workspace-stg, workspace-prd)
# Usando wildcard * para cobrir todos os inquilinos de nível 1
az network dns record-set a add-record -g $RESOURCE_GROUP -z $DNS_ZONE -n "*" -a $LOAD_BALANCER_IP

# Registro Nested (plataform.teamblue-stg)
az network dns record-set a add-record -g $RESOURCE_GROUP -z $DNS_ZONE -n "plataform.teamblue-stg" -a $LOAD_BALANCER_IP

echo "✅ Sucesso! Os domínios workspace-stg, workspace-prd e plataform.teamblue-stg estão roteados."
