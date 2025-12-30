terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
  required_version = ">= 1.2.0"
}

provider "azurerm" {
  features {}

  # Usa variável subscription_id se fornecida, senão usa ARM_SUBSCRIPTION_ID automaticamente
  subscription_id = var.subscription_id != "" ? var.subscription_id : null
  # Se subscription_id for null, o provider usa automaticamente ARM_SUBSCRIPTION_ID da variável de ambiente
}

# Data source para validar Resource Group existente (opcional)
data "azurerm_resource_group" "existing" {
  count = var.check_existing_resources ? 1 : 0
  name  = var.resource_group_name
}

# 1. Resource Group
resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location

  tags = {
    Environment = var.environment
    Project     = "AI-SaaS"
    Workspace   = terraform.workspace
  }

  # prevent_destroy removido: Terraform não permite expressões condicionais em lifecycle blocks
  # Para proteger recursos em produção, use: terraform destroy -target=... ou proteção via políticas Azure
}

# 2. Virtual Network
resource "azurerm_virtual_network" "main" {
  name                = "ai-saas-vnet-${var.environment}"
  address_space       = ["10.0.0.0/16"]
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  tags = {
    Environment = var.environment
    Project     = "AI-SaaS"
    Workspace   = terraform.workspace
  }

  lifecycle {
    create_before_destroy = true
  }
}

# 3. Subnet (VM)
resource "azurerm_subnet" "main" {
  name                 = "ai-saas-subnet-${var.environment}"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.1.0/24"]
}

# 3.1. Subnet para Azure Bastion (obrigatória)
resource "azurerm_subnet" "bastion" {
  count                = var.enable_bastion ? 1 : 0
  name                 = "AzureBastionSubnet"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.2.0/27"] # /27 é o tamanho mínimo para Bastion
}

# 4. Public IP (VM)
resource "azurerm_public_ip" "main" {
  name                = "ai-saas-public-ip-${var.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  allocation_method   = "Static"
  sku                 = "Standard"

  tags = {
    Environment = var.environment
    Project     = "AI-SaaS"
    Workspace   = terraform.workspace
  }
}

# 4.1. Public IP para Azure Bastion
resource "azurerm_public_ip" "bastion" {
  count               = var.enable_bastion ? 1 : 0
  name                = "ai-saas-bastion-ip-${var.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  allocation_method   = "Static"
  sku                 = "Standard"

  tags = {
    Environment = var.environment
    Project     = "AI-SaaS"
    Workspace   = terraform.workspace
  }
}

# 5. Network Security Group (Firewall)
resource "azurerm_network_security_group" "main" {
  name                = "ai-saas-nsg-${var.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  # SSH - Apenas se Bastion estiver desabilitado (legado)
  # CRÍTICO: Com Bastion habilitado, porta 22 não precisa estar aberta publicamente
  dynamic "security_rule" {
    for_each = var.enable_bastion ? {} : { for idx, cidr in var.allowed_ssh_ips : idx => cidr }
    content {
      name                       = "SSH-${replace(replace(security_rule.value, "/", "-"), ".", "-")}"
      priority                   = 1001 + tonumber(security_rule.key)
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "22"
      source_address_prefix      = security_rule.value
      destination_address_prefix = "*"
    }
  }

  # Frontend (Next.js) - Público somente se explicitamente permitido
  dynamic "security_rule" {
    for_each = var.frontend_public_access ? { 0 = "*" } : { for idx, cidr in var.allowed_frontend_ips : idx => cidr }
    content {
      name                       = var.frontend_public_access ? "Frontend-Public" : "Frontend-${replace(replace(security_rule.value, "/", "-"), ".", "-")}"
      priority                   = 2001 + tonumber(security_rule.key)
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "3000"
      source_address_prefix      = security_rule.value
      destination_address_prefix = "*"
    }
  }

  # Backend (FastAPI) - Público somente se explicitamente permitido
  dynamic "security_rule" {
    for_each = var.backend_public_access ? { 0 = "*" } : { for idx, cidr in var.allowed_backend_ips : idx => cidr }
    content {
      name                       = var.backend_public_access ? "Backend-Public" : "Backend-${replace(replace(security_rule.value, "/", "-"), ".", "-")}"
      priority                   = 3001 + tonumber(security_rule.key)
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "8000"
      source_address_prefix      = security_rule.value
      destination_address_prefix = "*"
    }
  }

  # HTTP (proxy) - Aberto conforme lista (default 0.0.0.0/0)
  # tfsec:ignore:azure-network-no-public-ingress - Acesso público necessário para frontend web
  dynamic "security_rule" {
    for_each = { for idx, cidr in var.allowed_http_ips : idx => cidr }
    content {
      name                       = "HTTP-${replace(replace(security_rule.value, "/", "-"), ".", "-")}"
      priority                   = 1501 + tonumber(security_rule.key)
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "80"
      source_address_prefix      = security_rule.value # tfsec:ignore:azure-network-no-public-ingress
      destination_address_prefix = "*"
    }
  }

  # HTTPS (proxy) - Aberto conforme lista (default 0.0.0.0/0)
  # tfsec:ignore:azure-network-no-public-ingress - Acesso público necessário para frontend web com HTTPS
  dynamic "security_rule" {
    for_each = { for idx, cidr in var.allowed_https_ips : idx => cidr }
    content {
      name                       = "HTTPS-${replace(replace(security_rule.value, "/", "-"), ".", "-")}"
      priority                   = 1502 + tonumber(security_rule.key)
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "443"
      source_address_prefix      = security_rule.value # tfsec:ignore:azure-network-no-public-ingress
      destination_address_prefix = "*"
    }
  }

  # PostgreSQL - Requer lista explícita; se vazio, porta 5433 permanece fechada
  dynamic "security_rule" {
    for_each = { for idx, cidr in var.allowed_postgres_ips : idx => cidr }
    content {
      name                       = "PostgreSQL-${replace(replace(security_rule.value, "/", "-"), ".", "-")}"
      priority                   = 4001 + tonumber(security_rule.key)
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "5433"
      source_address_prefix      = security_rule.value
      destination_address_prefix = "*"
    }
  }

  tags = {
    Environment = var.environment
    Project     = "AI-SaaS"
    Workspace   = terraform.workspace
  }
}

# 6. Network Interface
resource "azurerm_network_interface" "main" {
  name                = "ai-saas-nic-${var.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.main.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.main.id
  }

  tags = {
    Environment = var.environment
    Project     = "AI-SaaS"
    Workspace   = terraform.workspace
  }
}

# Associar NSG à Network Interface
resource "azurerm_network_interface_security_group_association" "main" {
  network_interface_id      = azurerm_network_interface.main.id
  network_security_group_id = azurerm_network_security_group.main.id
}

# Data source para validar VM existente (opcional)
data "azurerm_virtual_machine" "existing" {
  count               = var.check_existing_resources ? 1 : 0
  name                = var.vm_name
  resource_group_name = var.resource_group_name
}

# 7. Virtual Machine
resource "azurerm_linux_virtual_machine" "main" {
  name                = var.vm_name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  size                = var.vm_size
  admin_username      = var.admin_username

  network_interface_ids = [
    azurerm_network_interface.main.id,
  ]

  # Disco do sistema
  os_disk {
    name                 = "ai-saas-os-disk-${var.environment}"
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
    disk_size_gb         = 30
  }

  # Imagem Ubuntu 22.04 LTS
  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  # Autenticação SSH
  # Se ssh_public_key for um caminho de arquivo, lê o conteúdo automaticamente
  dynamic "admin_ssh_key" {
    for_each = var.ssh_public_key != "" ? [1] : []
    content {
      username = var.admin_username
      # Se começar com ./, ../ ou /, trata como caminho de arquivo
      public_key = startswith(var.ssh_public_key, "./") || startswith(var.ssh_public_key, "../") || startswith(var.ssh_public_key, "/") ? file(var.ssh_public_key) : var.ssh_public_key
    }
  }

  # Desabilitar autenticação por senha (mais seguro) - sempre desabilitado, usar apenas chaves SSH
  disable_password_authentication = true

  tags = {
    Name        = "AI-SaaS-${title(var.environment)}"
    Environment = var.environment
    Project     = "AI-SaaS"
    Workspace   = terraform.workspace
  }

  lifecycle {
    # prevent_destroy removido: Terraform não permite expressões condicionais em lifecycle blocks
    # Para proteger recursos em produção, use: terraform destroy -target=... ou proteção via políticas Azure
    ignore_changes = [tags["Workspace"]] # Ignorar mudanças no workspace tag
  }
}

# 8. Azure Bastion (Acesso SSH seguro sem expor porta 22)
# CRÍTICO: Migração de SSH público para acesso seguro via Bastion
resource "azurerm_bastion_host" "main" {
  count               = var.enable_bastion ? 1 : 0
  name                = "ai-saas-bastion-${var.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  # Alinhar com o recurso existente no Azure para evitar replacement (delete+create)
  sku = "Standard"

  ip_configuration {
    # Alinhar com o recurso existente no Azure para evitar replacement (delete+create)
    name                 = "bastion_ip_config"
    subnet_id            = azurerm_subnet.bastion[0].id
    public_ip_address_id = azurerm_public_ip.bastion[0].id
  }

  tags = {
    Environment = var.environment
    Project     = "AI-SaaS"
    Workspace   = terraform.workspace
  }
}
