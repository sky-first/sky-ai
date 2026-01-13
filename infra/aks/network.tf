resource "azurerm_virtual_network" "aks" {
  name                = "sky-aks-vnet-${var.environment}"
  location            = azurerm_resource_group.aks.location
  resource_group_name = azurerm_resource_group.aks.name
  address_space       = var.vnet_address_space

  tags = {
    Environment = var.environment
  }
}

# Subnet for AKS Nodes
resource "azurerm_subnet" "aks" {
  name                 = "aks-subnet"
  resource_group_name  = azurerm_resource_group.aks.name
  virtual_network_name = azurerm_virtual_network.aks.name
  # Calculate /22 subnet (0-3)
  address_prefixes = [cidrsubnet(var.vnet_address_space[0], 6, 0)]
}



# Subnet for Bastion VM
resource "azurerm_subnet" "bastion" {
  name                 = "bastion-subnet"
  resource_group_name  = azurerm_resource_group.aks.name
  virtual_network_name = azurerm_virtual_network.aks.name
  # Calculate /24 subnet (6)
  address_prefixes = [cidrsubnet(var.vnet_address_space[0], 8, 6)]
}

# NSG for Bastion
resource "azurerm_network_security_group" "bastion" {
  name                = "bastion-nsg-${var.environment}"
  location            = azurerm_resource_group.aks.location
  resource_group_name = azurerm_resource_group.aks.name

  dynamic "security_rule" {
    for_each = { for idx, ip in var.allowed_ssh_ips : idx => ip }
    content {
      name                       = "SSH-Access-${security_rule.key}"
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

  tags = {
    Environment = var.environment
  }
}

resource "azurerm_subnet_network_security_group_association" "bastion" {
  subnet_id                 = azurerm_subnet.bastion.id
  network_security_group_id = azurerm_network_security_group.bastion.id
}
