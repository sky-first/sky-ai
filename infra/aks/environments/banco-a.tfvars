# =============================================================================
# Cliente: Banco A
# Plano: Standard (sem Geo-DR)
# Onboarding: scripts/new-client.sh --client banco-a --dr false
# =============================================================================

environment         = "banco-a"
resource_group_name = "sky-aks-banco-a-rg"
aks_cluster_name    = "sky-aks-banco-a"
dns_prefix          = "sky-banco-a"
location            = "eastus2"

vnet_address_space = ["10.10.0.0/16"]
service_cidr       = "10.11.0.0/16"

admin_username = "azureuser"

authorized_ips = [
  # Preencher com IPs do cliente e do time de DevOps
]

allowed_ssh_ips = [
  # Preencher com IPs autorizados para SSH
]

# =============================================================================
# Geo-Disaster Recovery — NÃO CONTRATADO
# Para ativar: alterar para true e rodar terraform apply
# =============================================================================
enable_geo_dr = false
