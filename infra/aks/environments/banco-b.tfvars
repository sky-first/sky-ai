# =============================================================================
# Cliente: Banco B
# Plano: VIP com Geo-DR
# Onboarding: scripts/new-client.sh --client banco-b --dr true
# RTO: 15-20 min | RPO: <30s PostgreSQL / <60s Redis
# Custo DR: ~$500-600/mês (cobrado ao cliente)
# =============================================================================

environment         = "banco-b"
resource_group_name = "sky-aks-banco-b-rg"
aks_cluster_name    = "sky-aks-banco-b"
dns_prefix          = "sky-banco-b"
location            = "eastus2"

vnet_address_space  = ["10.20.0.0/16"]
service_cidr        = "10.21.0.0/16"

admin_username = "azureuser"

authorized_ips = [
  # Preencher com IPs do cliente e do time de DevOps
]

allowed_ssh_ips = [
  # Preencher com IPs autorizados para SSH
]

# =============================================================================
# Geo-Disaster Recovery — ATIVO
# Região secundária: centralus (par da eastus2 na Azure)
# =============================================================================
enable_geo_dr = true

dr_location            = "centralus"
dr_resource_group_name = "sky-aks-banco-b-dr-rg"
dr_vnet_address_space  = "10.22.0.0/16"

dr_postgres_sku   = "GP_Standard_D2s_v3"
dr_redis_capacity = 1

# Preencher após terraform apply (obtido via: terraform output)
dr_primary_origin_hostname   = "workspace.bancob.com.br"
dr_secondary_origin_hostname = "workspace-dr.bancob.com.br"
