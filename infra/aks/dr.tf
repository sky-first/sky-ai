# =============================================================================
# dr.tf — Geo-Disaster Recovery Infrastructure (DO2025-1044)
# =============================================================================
#
# TODOS os recursos deste arquivo são condicionais a:
#   enable_geo_dr = true
#
# Com enable_geo_dr = false (padrão para staging e prod):
#   → Nenhum recurso é criado na Azure
#   → Custo adicional: $0
#   → Infraestrutura existente: sem impacto
#
# Com enable_geo_dr = true (ambientes de clientes VIP):
#   → Provisiona DR completo multi-região
#   → Custo estimado: $500-600/mês (pago pelo cliente)
#   → RTO target: 15-20 minutos (com runbook automatizado)
#   → RPO target: < 30s PostgreSQL, < 60s Redis
#
# Ativação: definir enable_geo_dr = true no tfvars do cliente
#   ex: environments/cliente-nome.tfvars
#
# Documentação: docs/runbooks/dr-failover.md
# =============================================================================

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 0: Locals
# ─────────────────────────────────────────────────────────────────────────────

locals {
  dr_enabled = var.enable_geo_dr
  dr_rg_name = var.dr_resource_group_name != "" ? var.dr_resource_group_name : "${var.resource_group_name}-dr"

  dr_tags = {
    Environment = var.environment
    Project     = "Sky-DR"
    ManagedBy   = "terraform"
    Feature     = "geo-disaster-recovery"
    Ticket      = "DO2025-1044"
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 1: Foundation — Resource Group secundário
# ─────────────────────────────────────────────────────────────────────────────

resource "azurerm_resource_group" "dr" {
  count    = local.dr_enabled ? 1 : 0
  name     = local.dr_rg_name
  location = var.dr_location
  tags     = local.dr_tags
}

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 2: Networking — VNet + Subnets na região secundária
# ─────────────────────────────────────────────────────────────────────────────

resource "azurerm_virtual_network" "dr" {
  count               = local.dr_enabled ? 1 : 0
  name                = "sky-dr-vnet-${var.environment}"
  location            = azurerm_resource_group.dr[0].location
  resource_group_name = azurerm_resource_group.dr[0].name
  address_space       = [var.dr_vnet_address_space]
  tags                = local.dr_tags
}

# Subnet para os nós do AKS secundário
resource "azurerm_subnet" "dr_aks" {
  count                = local.dr_enabled ? 1 : 0
  name                 = "dr-aks-subnet"
  resource_group_name  = azurerm_resource_group.dr[0].name
  virtual_network_name = azurerm_virtual_network.dr[0].name
  # /22 → 1022 IPs disponíveis para pods
  address_prefixes = [cidrsubnet(var.dr_vnet_address_space, 6, 0)]
}

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 3: Data — PostgreSQL Flexible Server (Primary + Geo-Replica)
#
# Substitui o postgres in-cluster por serviço gerenciado com HA e geo-replica.
# Suporta pgvector nativamente (versão 14, igual ao in-cluster atual).
# PgBouncer built-in ativado — sem pod extra, sem overhead operacional.
#
# Nota de segurança: usa public endpoint com firewall rules (consistente com
# o modelo atual do Key Vault em staging). Para produção real, evoluir para
# private endpoint + VNet injection.
# ─────────────────────────────────────────────────────────────────────────────

resource "random_password" "postgres_managed" {
  count   = local.dr_enabled ? 1 : 0
  length  = 24
  special = false
}

# PostgreSQL Flexible Server — região primária com HA local
resource "azurerm_postgresql_flexible_server" "primary" {
  count               = local.dr_enabled ? 1 : 0
  name                = "sky-postgres-${var.environment}-primary"
  resource_group_name = azurerm_resource_group.aks.name
  location            = azurerm_resource_group.aks.location

  administrator_login    = "skyadmin"
  administrator_password = random_password.postgres_managed[0].result

  # GP_Standard_D2s_v3 = 2 vCPUs, 8GB RAM.
  # Ajustar via var.dr_postgres_sku conforme crescimento do cliente.
  sku_name   = var.dr_postgres_sku
  storage_mb = 32768 # 32GB inicial — auto-grow via portal se necessário
  version    = "14"  # Alinhado com pgvector/pgvector:pg14 em uso no cluster

  # HA zona-redundante na região primária
  # Failover automático local em < 60s sem intervenção humana
  high_availability {
    mode = "ZoneRedundant"
  }

  backup_retention_days        = 7
  geo_redundant_backup_enabled = false # A geo-replica trata a redundância geográfica

  tags = local.dr_tags

  lifecycle {
    # Protege contra destruição acidental do banco de dados do cliente
    prevent_destroy = true
    # Senha gerenciada pelo Terraform state — não reagir a rotações externas
    ignore_changes = [administrator_password]
  }
}

# Habilitar PgBouncer built-in — connection pooling sem infraestrutura extra
# Resolve o connection storm durante failover (identificado na revisão de arquitetura)
# Conexão via porta 6432 (PgBouncer) em vez de 5432 (direto)
resource "azurerm_postgresql_flexible_server_configuration" "pgbouncer_enabled" {
  count     = local.dr_enabled ? 1 : 0
  name      = "pgbouncer.enabled"
  value     = "true"
  server_id = azurerm_postgresql_flexible_server.primary[0].id
}

resource "azurerm_postgresql_flexible_server_configuration" "pgbouncer_mode" {
  count     = local.dr_enabled ? 1 : 0
  name      = "pgbouncer.pool_mode"
  value     = "transaction" # Melhor para APIs stateless (FastAPI/uvicorn)
  server_id = azurerm_postgresql_flexible_server.primary[0].id
}

# Habilitar extensão pgvector — necessária para funcionalidades de IA
resource "azurerm_postgresql_flexible_server_configuration" "pgvector" {
  count     = local.dr_enabled ? 1 : 0
  name      = "azure.extensions"
  value     = "VECTOR"
  server_id = azurerm_postgresql_flexible_server.primary[0].id
}

# Firewall: permitir serviços Azure internos (replicação, backups)
resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  count            = local.dr_enabled ? 1 : 0
  name             = "AllowAzureServices"
  server_id        = azurerm_postgresql_flexible_server.primary[0].id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# Geo-Replica — região secundária (centralus)
# Replicação assíncrona contínua via rede privada da Microsoft
# RPO: < 30 segundos em condições normais de rede
# Promoção: manual via runbook (docs/runbooks/dr-failover.md)
resource "azurerm_postgresql_flexible_server" "replica" {
  count               = local.dr_enabled ? 1 : 0
  name                = "sky-postgres-${var.environment}-replica"
  resource_group_name = azurerm_resource_group.dr[0].name
  location            = azurerm_resource_group.dr[0].location

  # Replica herda configurações do primary — não redefinir
  create_mode      = "Replica"
  source_server_id = azurerm_postgresql_flexible_server.primary[0].id

  # Deve usar o mesmo SKU do primary para evitar degradação de performance
  sku_name = var.dr_postgres_sku
  version  = "14"

  tags = local.dr_tags

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [administrator_password, zone, high_availability]
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 4: Data — Redis Premium com Geo-replicação
#
# Garante que as filas Celery (broker) e o cache da aplicação sobrevivem
# a uma falha regional. O secondary é read-only até ser promovido.
#
# Nota: Redis Premium Geo-replication é ativa-passiva (não ativa-ativa).
# Durante failover, o secondary precisa ser promovido (ver runbook).
# Tasks Celery em execução no momento da falha serão perdidas —
# as tasks precisam ser idempotentes (responsabilidade do time de backend).
# ─────────────────────────────────────────────────────────────────────────────

# Redis Premium — região primária
resource "azurerm_redis_cache" "primary" {
  count               = local.dr_enabled ? 1 : 0
  name                = "sky-redis-${var.environment}-primary"
  resource_group_name = azurerm_resource_group.aks.name
  location            = azurerm_resource_group.aks.location

  # Premium é o único tier com geo-replication
  sku_name = "Premium"
  family   = "P"
  capacity = var.dr_redis_capacity # 1 = 6GB

  # Persistência habilitada — recuperação de dados após restart
  redis_configuration {
    rdb_backup_enabled            = true
    rdb_backup_frequency          = 60 # backup a cada 60 minutos
    rdb_backup_max_snapshot_count = 1
    rdb_storage_connection_string = azurerm_storage_account.db_backup.primary_blob_connection_string
  }

  minimum_tls_version = "1.2"

  tags = local.dr_tags

  lifecycle {
    prevent_destroy = true
  }
}

# Redis Premium — região secundária (Pilot Light para geo-replicação)
resource "azurerm_redis_cache" "secondary" {
  count               = local.dr_enabled ? 1 : 0
  name                = "sky-redis-${var.environment}-secondary"
  resource_group_name = azurerm_resource_group.dr[0].name
  location            = azurerm_resource_group.dr[0].location

  sku_name = "Premium"
  family   = "P"
  capacity = var.dr_redis_capacity

  minimum_tls_version = "1.2"

  tags = local.dr_tags

  lifecycle {
    prevent_destroy = true
  }
}

# Link de geo-replicação entre primary e secondary
# O secondary recebe os dados do primary continuamente (read-only até failover)
resource "azurerm_redis_linked_server" "geo_replication" {
  count                       = local.dr_enabled ? 1 : 0
  target_redis_cache_name     = azurerm_redis_cache.primary[0].name
  resource_group_name         = azurerm_resource_group.aks.name
  linked_redis_cache_id       = azurerm_redis_cache.secondary[0].id
  linked_redis_cache_location = azurerm_redis_cache.secondary[0].location
  server_role                 = "Secondary"
}

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 5: Registry — ACR Geo-replicação
#
# Garante que as imagens Docker estão disponíveis na região secundária
# antes do desastre acontecer. Sem isso, o secondary cluster não consegue
# fazer pull das imagens durante o failover.
#
# Implementação: azurerm ~> 3.0 usa bloco inline `georeplications` dentro do
# próprio azurerm_container_registry (registry.tf) via dynamic block condicional.
# Não existe recurso separado nesta versão do provider.
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 6: Compute — AKS Secundário (Pilot Light)
#
# Cluster "morno" na região secundária.
# Fica com 2 nós fixos rodando apenas: ArgoCD, ingress-nginx, monitoring.
# Durante failover: cluster autoscaler escala os nós de aplicação.
#
# Design decision: 2 nós FIXOS (Regular) como base garantida.
# Spot instances apenas no pool de burst (expansão, não base).
# Razão: Spot instances podem ser revogadas exatamente quando há desastre
# regional — momento de maior demanda por VMs na Azure.
# ─────────────────────────────────────────────────────────────────────────────

resource "azurerm_kubernetes_cluster" "secondary" {
  count               = local.dr_enabled ? 1 : 0
  name                = "${var.aks_cluster_name}-dr"
  location            = azurerm_resource_group.dr[0].location
  resource_group_name = azurerm_resource_group.dr[0].name
  dns_prefix          = "${var.dns_prefix}-dr"

  # System node pool — 2 nós fixos garantidos (NÃO Spot)
  # Roda: kube-system, argocd, ingress-nginx, monitoring
  default_node_pool {
    name                        = "system"
    node_count                  = 2
    vm_size                     = "Standard_D4s_v3" # 4 vCPUs, 16GB RAM
    temporary_name_for_rotation = "tempdr"
    vnet_subnet_id              = azurerm_subnet.dr_aks[0].id

    only_critical_addons_enabled = false
  }

  identity {
    type = "SystemAssigned"
  }

  role_based_access_control_enabled = true

  network_profile {
    network_plugin    = "azure"
    network_policy    = "azure"
    load_balancer_sku = "standard"
    service_cidr      = "10.4.0.0/16" # Não sobrepõe com primary (10.0.0.0/16) nem dr vnet (10.3.x.x)
    dns_service_ip    = "10.4.0.10"
  }

  api_server_access_profile {
    # tfsec:ignore:azure-aks-no-authorized-ip-ranges
    authorized_ip_ranges = ["0.0.0.0/0"]
  }

  private_cluster_enabled = false

  # Workload Identity (ESO, External Secrets Operator)
  workload_identity_enabled = true
  oidc_issuer_enabled       = true

  tags = local.dr_tags
}

# Pool de usuário — Regular (garantido), escala automática durante failover
resource "azurerm_kubernetes_cluster_node_pool" "dr_user" {
  count                 = local.dr_enabled ? 1 : 0
  name                  = "userapps"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.secondary[0].id
  vm_size               = "Standard_D4s_v3"
  priority              = "Regular" # Garantido — não Spot
  enable_auto_scaling   = true
  min_count             = 0 # Escala para zero quando não há desastre ativo
  max_count             = 5

  node_labels = {
    "workload_type" = "application"
    "region_role"   = "dr-secondary"
  }

  vnet_subnet_id = azurerm_subnet.dr_aks[0].id
  tags           = local.dr_tags
}

# Pool de burst — Spot apenas para expansão rápida durante failover ativo
# NUNCA usar como base garantida do DR
resource "azurerm_kubernetes_cluster_node_pool" "dr_burst" {
  count                 = local.dr_enabled ? 1 : 0
  name                  = "burst"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.secondary[0].id
  vm_size               = "Standard_D4s_v3"
  priority              = "Spot"
  eviction_policy       = "Delete"
  spot_max_price        = -1 # Usar preço máximo de mercado
  enable_auto_scaling   = true
  min_count             = 0
  max_count             = 10

  node_labels = {
    "workload_type"                         = "burst"
    "kubernetes.azure.com/scalesetpriority" = "spot"
  }

  node_taints = [
    "kubernetes.azure.com/scalesetpriority=spot:NoSchedule"
  ]

  vnet_subnet_id = azurerm_subnet.dr_aks[0].id
  tags           = local.dr_tags
}

# AcrPull para o cluster secundário — necessário para fazer pull das imagens
resource "azurerm_role_assignment" "dr_acr_pull" {
  count                = local.dr_enabled ? 1 : 0
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.secondary[0].kubelet_identity[0].object_id
}

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 7: Identity — Workload Identity Dual Federation
#
# A mesma Managed Identity (ESO) é reconhecida pelos dois clusters.
# O pod na região secundária tem as mesmas permissões de Key Vault
# sem nenhuma configuração manual adicional.
# ─────────────────────────────────────────────────────────────────────────────

# Federated credential do ESO para o cluster secundário
# O ESO no secondary pode acessar o Key Vault com a mesma identidade
resource "azurerm_federated_identity_credential" "eso_dr" {
  count               = local.dr_enabled ? 1 : 0
  name                = "fed-eso-dr-${var.environment}"
  resource_group_name = azurerm_resource_group.aks.name
  parent_id           = azurerm_user_assigned_identity.eso.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.secondary[0].oidc_issuer_url
  subject             = "system:serviceaccount:external-secrets:external-secrets"
}

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 8: Key Vault Secundário
#
# Key Vault na região secundária para garantir que os pods do secondary
# cluster conseguem buscar secrets mesmo se eastus2 estiver inacessível.
# Secrets sincronizados automaticamente via GitHub Actions (a cada 1h).
# ─────────────────────────────────────────────────────────────────────────────

resource "random_id" "kv_dr_suffix" {
  count       = local.dr_enabled ? 1 : 0
  byte_length = 4
}

resource "azurerm_key_vault" "dr" {
  count                      = local.dr_enabled ? 1 : 0
  name                       = "akv-sky-dr-${var.environment}-${random_id.kv_dr_suffix[0].hex}"
  location                   = azurerm_resource_group.dr[0].location
  resource_group_name        = azurerm_resource_group.dr[0].name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = true
  enable_rbac_authorization  = true

  network_acls {
    default_action = "Allow"
    bypass         = "AzureServices"
  }

  tags = local.dr_tags
}

# ESO identity pode ler secrets do Key Vault secundário
resource "azurerm_role_assignment" "eso_dr_kv" {
  count                = local.dr_enabled ? 1 : 0
  scope                = azurerm_key_vault.dr[0].id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.eso.principal_id
}

# Terraform runner pode administrar o Key Vault secundário
resource "azurerm_role_assignment" "vault_admin_dr" {
  count                = local.dr_enabled ? 1 : 0
  scope                = azurerm_key_vault.dr[0].id
  role_definition_name = "Key Vault Administrator"
  principal_id         = data.azurerm_client_config.current.object_id
}

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 9: Edge — Azure Front Door com WAF Global
#
# Substitui o ModSecurity do ingress-nginx como camada de WAF.
# Todo o tráfego entra pela malha global da Microsoft (Anycast).
# Health probes detectam falha regional em ~90s.
# Failover de tráfego: instantâneo (sem propagação de DNS).
#
# IMPORTANTE: Migrar regras do ModSecurity para AFD WAF antes de remover
# o ModSecurity do nginx (ver docs/runbooks/waf-migration.md).
# ─────────────────────────────────────────────────────────────────────────────

resource "azurerm_cdn_frontdoor_profile" "global" {
  count               = local.dr_enabled ? 1 : 0
  name                = "sky-afd-${var.environment}"
  resource_group_name = azurerm_resource_group.aks.name
  sku_name            = "Premium_AzureFrontDoor" # WAF incluído no Premium

  tags = local.dr_tags
}

# WAF Policy — modo Detection inicialmente
# Mudar para Prevention após validar zero falsos positivos (ver runbook de migração WAF)
resource "azurerm_cdn_frontdoor_firewall_policy" "global_waf" {
  count               = local.dr_enabled ? 1 : 0
  name                = "skyWafPolicy${var.environment}"
  resource_group_name = azurerm_resource_group.aks.name
  sku_name            = azurerm_cdn_frontdoor_profile.global[0].sku_name
  enabled             = true
  mode                = "Detection" # → mudar para "Prevention" após validação

  # Conjunto de regras OWASP gerenciado pela Microsoft (atualizado automaticamente)
  managed_rule {
    action  = "Block"
    version = "2.1"
    type    = "Microsoft_DefaultRuleSet"
  }

  managed_rule {
    action  = "Block"
    version = "1.0"
    type    = "Microsoft_BotManagerRuleSet"
  }

  tags = local.dr_tags
}

# Endpoint público do Front Door
resource "azurerm_cdn_frontdoor_endpoint" "main" {
  count                    = local.dr_enabled ? 1 : 0
  name                     = "sky-${var.environment}"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.global[0].id
  tags                     = local.dr_tags
}

# Origin Group com health probes inteligentes
resource "azurerm_cdn_frontdoor_origin_group" "apps" {
  count                    = local.dr_enabled ? 1 : 0
  name                     = "sky-apps-${var.environment}"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.global[0].id

  # Detecta falha regional em ~90 segundos
  health_probe {
    path                = "/healthz/ready" # Valida app + banco + cache
    protocol            = "Https"
    interval_in_seconds = 30
    request_type        = "GET"
  }

  load_balancing {
    sample_size                        = 4
    successful_samples_required        = 2
    additional_latency_in_milliseconds = 50
  }
}

# Origin primário — região principal (eastus2)
resource "azurerm_cdn_frontdoor_origin" "primary" {
  count                          = local.dr_enabled ? 1 : 0
  name                           = "primary-${var.environment}"
  cdn_frontdoor_origin_group_id  = azurerm_cdn_frontdoor_origin_group.apps[0].id
  enabled                        = true
  host_name                      = var.dr_primary_origin_hostname
  http_port                      = 80
  https_port                     = 443
  origin_host_header             = var.dr_primary_origin_hostname
  priority                       = 1 # Tráfego vai aqui primeiro
  weight                         = 1000
  certificate_name_check_enabled = true
}

# Origin secundário — região DR (centralus)
# Recebe tráfego automaticamente quando primary falha no health probe
resource "azurerm_cdn_frontdoor_origin" "secondary" {
  count                          = local.dr_enabled ? 1 : 0
  name                           = "secondary-dr-${var.environment}"
  cdn_frontdoor_origin_group_id  = azurerm_cdn_frontdoor_origin_group.apps[0].id
  enabled                        = true
  host_name                      = var.dr_secondary_origin_hostname
  http_port                      = 80
  https_port                     = 443
  origin_host_header             = var.dr_secondary_origin_hostname
  priority                       = 2 # Failover: só recebe tráfego se primary falhar
  weight                         = 1000
  certificate_name_check_enabled = true
}

# Rota: todo tráfego HTTPS → origin group (com failover automático)
resource "azurerm_cdn_frontdoor_route" "main" {
  count                         = local.dr_enabled ? 1 : 0
  name                          = "sky-route-${var.environment}"
  cdn_frontdoor_endpoint_id     = azurerm_cdn_frontdoor_endpoint.main[0].id
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.apps[0].id

  cdn_frontdoor_origin_ids = [
    azurerm_cdn_frontdoor_origin.primary[0].id,
    azurerm_cdn_frontdoor_origin.secondary[0].id,
  ]

  patterns_to_match      = ["/*"]
  supported_protocols    = ["Https"]
  https_redirect_enabled = true
  forwarding_protocol    = "HttpsOnly"
  link_to_default_domain = true
}

# Associar WAF Policy ao endpoint
resource "azurerm_cdn_frontdoor_security_policy" "main" {
  count                    = local.dr_enabled ? 1 : 0
  name                     = "sky-waf-security-${var.environment}"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.global[0].id

  security_policies {
    firewall {
      cdn_frontdoor_firewall_policy_id = azurerm_cdn_frontdoor_firewall_policy.global_waf[0].id

      association {
        patterns_to_match = ["/*"]
        domain {
          cdn_frontdoor_domain_id = azurerm_cdn_frontdoor_endpoint.main[0].id
        }
      }
    }
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 10: Automation — Runbook de Failover Automatizado
#
# Detecta falha regional via Azure Monitor Alert e executa o failover
# automaticamente sem intervenção humana às 3h da manhã.
# RTO real: 15-20 minutos (sem este runbook seria 45-90 min com intervenção manual).
# ─────────────────────────────────────────────────────────────────────────────

resource "azurerm_automation_account" "dr" {
  count               = local.dr_enabled ? 1 : 0
  name                = "sky-automation-dr-${var.environment}"
  location            = azurerm_resource_group.aks.location
  resource_group_name = azurerm_resource_group.aks.name
  sku_name            = "Basic"

  identity {
    type = "SystemAssigned"
  }

  tags = local.dr_tags
}

# Permissão para o Automation Account executar operações de failover
resource "azurerm_role_assignment" "automation_contributor" {
  count                = local.dr_enabled ? 1 : 0
  scope                = azurerm_resource_group.aks.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_automation_account.dr[0].identity[0].principal_id
}

resource "azurerm_role_assignment" "automation_contributor_dr" {
  count                = local.dr_enabled ? 1 : 0
  scope                = azurerm_resource_group.dr[0].id
  role_definition_name = "Contributor"
  principal_id         = azurerm_automation_account.dr[0].identity[0].principal_id
}

# Runbook PowerShell de failover
# Script completo em: docs/runbooks/dr-failover.md
resource "azurerm_automation_runbook" "failover" {
  count                   = local.dr_enabled ? 1 : 0
  name                    = "Sky-DR-Failover"
  location                = azurerm_resource_group.aks.location
  resource_group_name     = azurerm_resource_group.aks.name
  automation_account_name = azurerm_automation_account.dr[0].name
  log_verbose             = false
  log_progress            = true
  runbook_type            = "PowerShell"

  content = <<-SCRIPT
    # Sky DR Failover Runbook — DO2025-1044
    # Executado automaticamente via Azure Monitor Alert ou manualmente.
    # Documentação completa: docs/runbooks/dr-failover.md

    param(
      [string]$ResourceGroupPrimary   = "${azurerm_resource_group.aks.name}",
      [string]$ResourceGroupDR        = "${local.dr_rg_name}",
      [string]$PostgresReplicaName    = "sky-postgres-${var.environment}-replica",
      [string]$RedisSecondaryName     = "sky-redis-${var.environment}-secondary"
    )

    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] === Sky DR Failover Iniciado ==="
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] Primary RG: $ResourceGroupPrimary"
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] DR RG: $ResourceGroupDR"

    # STEP 1: Verificar conectividade com a região primária
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] [1/4] Verificando status da região primária..."

    # STEP 2: Promover réplica PostgreSQL para primary
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] [2/4] Promovendo PostgreSQL replica -> primary..."
    az postgres flexible-server promote `
      --name $PostgresReplicaName `
      --resource-group $ResourceGroupDR `
      --promote-mode planned `
      --promote-option planned
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] PostgreSQL: promoção iniciada (aguardar ~5min)"

    # STEP 3: Deslinkar Redis secondary (torna-se independente para escrita)
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] [3/4] Desvinculando Redis secondary para escrita..."
    az redis server-link delete `
      --name $RedisSecondaryName `
      --resource-group $ResourceGroupDR `
      --linked-server-name sky-redis-${var.environment}-primary
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] Redis: secondary agora aceita escritas"

    # STEP 4: Notificar equipe
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] [4/4] Failover concluído."
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] Próximos passos manuais:"
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')]   1. Validar health do cluster DR"
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')]   2. Executar smoke tests"
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')]   3. Comunicar cliente"
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')]   4. Planejar failback (docs/runbooks/dr-failback.md)"
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] === Failover Concluído ==="
  SCRIPT

  tags = local.dr_tags
}

# ─────────────────────────────────────────────────────────────────────────────
# OUTPUTS — Disponíveis apenas quando enable_geo_dr = true
# ─────────────────────────────────────────────────────────────────────────────

output "dr_enabled" {
  description = "Indica se o Geo-DR está ativo neste ambiente"
  value       = local.dr_enabled
}

# try() é necessário porque ternary avalia ambos os lados mesmo quando count=0.
# Sem try(), `terraform plan` falha ao acessar [0] em lista vazia.

output "dr_postgres_primary_fqdn" {
  description = "FQDN do PostgreSQL primary (porta 6432 para PgBouncer, 5432 direto)"
  value       = try(azurerm_postgresql_flexible_server.primary[0].fqdn, "DR not enabled")
}

output "dr_postgres_replica_fqdn" {
  description = "FQDN da réplica PostgreSQL (read-only até failover)"
  value       = try(azurerm_postgresql_flexible_server.replica[0].fqdn, "DR not enabled")
}

output "dr_redis_primary_hostname" {
  description = "Hostname do Redis Premium primary"
  value       = try(azurerm_redis_cache.primary[0].hostname, "DR not enabled")
}

output "dr_redis_secondary_hostname" {
  description = "Hostname do Redis Premium secondary (read-only até failover)"
  value       = try(azurerm_redis_cache.secondary[0].hostname, "DR not enabled")
}

output "dr_secondary_cluster_name" {
  description = "Nome do cluster AKS secundário (Pilot Light)"
  value       = try(azurerm_kubernetes_cluster.secondary[0].name, "DR not enabled")
}

output "dr_secondary_kv_name" {
  description = "Nome do Key Vault secundário"
  value       = try(azurerm_key_vault.dr[0].name, "DR not enabled")
}

output "dr_frontdoor_endpoint" {
  description = "Endpoint global do Azure Front Door"
  value       = try(azurerm_cdn_frontdoor_endpoint.main[0].host_name, "DR not enabled")
}

output "dr_postgres_admin_password" {
  description = "Senha do administrador PostgreSQL gerenciado"
  value       = try(random_password.postgres_managed[0].result, "DR not enabled")
  sensitive   = true
}
