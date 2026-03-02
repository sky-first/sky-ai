environment         = "staging"
resource_group_name = "rg-sky-teamblue-stg"
aks_cluster_name    = "aks-sky-tb-stg"
dns_prefix          = "sky-tb-stg"
location            = "eastus2"
vnet_address_space  = ["10.2.0.0/16"] # Rede isolada para a Team.Blue
oidc_issuer_url     = "https://eastus2.oic.prod-aks.azure.com/a1b3ce06-b7ba-4d99-8a26-3347ab865f36/ced8a7d9-87f8-4b49-b213-9d6f79eb0bee/"

tags = {
  Client      = "Team.Blue"
  Environment = "Staging"
  Simulation  = "true"
}

# Configuração de DNS (Herda da infra core do staging)
external_dns_identity_resource_group = "rg-core-infra-prd"

# IPs autorizados (mesmos do staging para facilitar seu acesso)
authorized_ips = [
  "81.84.211.111/32",
  "169.155.237.0/24",
  "20.97.244.91/32",
  "135.18.146.170/32",
  "87.196.81.172/32",
  "87.196.80.186/32", # IP Detectado no terminal
]

allowed_ssh_ips = [
  "81.84.211.111/32",
  "169.155.237.0/24",
  "20.97.244.91/32",
  "135.18.146.170/32",
  "87.196.81.172/32",
]

# Service Principal do GitHub para o cofre
github_actions_sp_object_id = "4eb2819d-b43b-4eb6-9d7f-f02b96088d1c"

# IP para bypass do firewall do Key Vault (Seu IP atual)
runner_ip = "87.196.80.186"
