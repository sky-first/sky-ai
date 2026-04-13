# Client: Banco VIP
# Environment: Production
# Strategy: Isolated (Mansion Model) + Geo-Disaster Recovery
# Ticket: DO2025-1044
# DR Cost: ~$500-600/month (billed to client)
# RTO: 15-20 min | RPO: <30s PostgreSQL / <60s Redis

environment         = "prod-vip"
aks_cluster_name    = "sky-aks-vip"
resource_group_name = "sky-aks-vip-rg"
dns_prefix          = "sky-vip"
location            = "eastus2"

# Dedicated Networking — no overlap with other environments
# Primary:  10.5.0.0/16 (eastus2)
# DR:       10.6.0.0/16 (centralus)
vnet_address_space = ["10.5.0.0/16"]
service_cidr       = "10.7.0.0/16" # Non-overlapping with VNet and DR VNet

# Larger Instance Sizes for Production
admin_username     = "vipadmin"
kubernetes_version = "1.29"

# =============================================================================
# Geo-Disaster Recovery (DO2025-1044) — ATIVADO para cliente VIP
# =============================================================================
enable_geo_dr = true

# Região secundária (par da eastus2 na Azure)
dr_location             = "centralus"
dr_resource_group_name  = "sky-aks-vip-dr-rg"
dr_vnet_address_space   = "10.6.0.0/16"

# PostgreSQL Flexible Server SKU — 2 vCPUs, 8GB RAM
# Aumentar para GP_Standard_D4s_v3 (4 vCPUs) se carga aumentar
dr_postgres_sku    = "GP_Standard_D2s_v3"

# Redis Premium capacity — 1=6GB, 2=13GB, 3=26GB
dr_redis_capacity  = 1

# Azure Front Door origins
# primary: hostname do Load Balancer do ingress-nginx em eastus2
# secondary: hostname do Load Balancer do ingress-nginx em centralus (DR)
# Preencher após criação dos clusters e obtenção dos IPs públicos.
dr_primary_origin_hostname   = "workspace-vip-api.skyfirstlabs.com"
dr_secondary_origin_hostname = "workspace-vip-dr-api.skyfirstlabs.com"
