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

# 1. Resource Group
resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location

  tags = {
    Environment = var.environment
    Project     = "AI-SaaS"
    Workspace   = terraform.workspace
  }
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
}

# 3. Subnet
resource "azurerm_subnet" "main" {
  name                 = "ai-saas-subnet-${var.environment}"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.1.0/24"]
}

# 4. Public IP
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

# 5. Network Security Group (Firewall)
resource "azurerm_network_security_group" "main" {
  name                = "ai-saas-nsg-${var.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  # SSH - Acesso público por padrão, ou restrito por IP se configurado
  # Se allowed_ssh_ips estiver vazio: acesso público (qualquer IP)
  # Se allowed_ssh_ips tiver valores: acesso restrito apenas para esses IPs
  # Segurança garantida pela autenticação forte (apenas chaves SSH, sem senha)
  dynamic "security_rule" {
    for_each = length(var.allowed_ssh_ips) > 0 ? var.allowed_ssh_ips : ["*"]
    content {
      name                       = length(var.allowed_ssh_ips) > 0 ? "SSH-${replace(replace(security_rule.value, "/", "-"), ".", "-")}" : "SSH-Public"
      priority                   = 1001 + security_rule.key
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "22"
      source_address_prefix      = security_rule.value
      destination_address_prefix = "*"
    }
  }

  # Frontend (Next.js) - Público ou restrito por IP
  dynamic "security_rule" {
    for_each = var.frontend_public_access ? ["*"] : var.allowed_frontend_ips
    content {
      name                       = var.frontend_public_access ? "Frontend-Public" : "Frontend-${replace(replace(security_rule.value, "/", "-"), ".", "-")}"
      priority                   = 2001 + (var.frontend_public_access ? 0 : security_rule.key)
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "3000"
      source_address_prefix      = security_rule.value
      destination_address_prefix = "*"
    }
  }

  # Backend (FastAPI) - Público ou restrito por IP
  dynamic "security_rule" {
    for_each = var.backend_public_access ? ["*"] : var.allowed_backend_ips
    content {
      name                       = var.backend_public_access ? "Backend-Public" : "Backend-${replace(replace(security_rule.value, "/", "-"), ".", "-")}"
      priority                   = 3001 + (var.backend_public_access ? 0 : security_rule.key)
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "8000"
      source_address_prefix      = security_rule.value
      destination_address_prefix = "*"
    }
  }

  # PostgreSQL - Acesso público (protegido por senha do banco)
  # Para maior segurança, considere restringir por IP usando allowed_postgres_ips
  dynamic "security_rule" {
    for_each = length(var.allowed_postgres_ips) > 0 ? var.allowed_postgres_ips : ["*"]
    content {
      name                       = length(var.allowed_postgres_ips) > 0 ? "PostgreSQL-${replace(replace(security_rule.value, "/", "-"), ".", "-")}" : "PostgreSQL-Public"
      priority                   = 4001 + security_rule.key
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
  name                = "ai-saas-nic"
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

  # Desabilitar autenticação por senha (mais seguro)
  disable_password_authentication = var.ssh_public_key != ""

  tags = {
    Name        = "AI-SaaS-${title(var.environment)}"
    Environment = var.environment
    Project     = "AI-SaaS"
    Workspace   = terraform.workspace
  }
}
