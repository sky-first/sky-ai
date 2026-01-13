# Client: Banco VIP
# Environment: Production
# Strategy: Isolated (Mansion Model)

environment         = "prod-vip"
aks_cluster_name    = "sky-aks-vip"
resource_group_name = "sky-aks-vip-rg"
dns_prefix          = "sky-vip"
location            = "eastus"

# Dedicated Networking (no overlap with staging if we peer later)
# Assuming main staging is 10.1.0.0/16
# We give this client 10.2.0.0/16
vnet_address_space = ["10.2.0.0/16"]
service_cidr       = "10.0.0.0/16" # Non-overlapping with VNet (10.2.x.x)

# Larger Instance Sizes for Production
admin_username     = "vipadmin"
kubernetes_version = "1.27"
