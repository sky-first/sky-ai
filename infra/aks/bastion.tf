resource "azurerm_public_ip" "bastion" {
  count               = var.ssh_public_key != null ? 1 : 0
  name                = "bastion-pip-${var.environment}"
  location            = azurerm_resource_group.aks.location
  resource_group_name = azurerm_resource_group.aks.name
  allocation_method   = "Static"
  sku                 = "Standard"
}

resource "azurerm_network_interface" "bastion" {
  count               = var.ssh_public_key != null ? 1 : 0
  name                = "bastion-nic-${var.environment}"
  location            = azurerm_resource_group.aks.location
  resource_group_name = azurerm_resource_group.aks.name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.bastion.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.bastion[0].id
  }
}

resource "azurerm_linux_virtual_machine" "bastion" {
  count               = var.ssh_public_key != null ? 1 : 0
  name                = "bastion-vm-${var.environment}"
  location            = azurerm_resource_group.aks.location
  resource_group_name = azurerm_resource_group.aks.name
  size                = "Standard_B1s"
  admin_username      = var.admin_username
  network_interface_ids = [
    azurerm_network_interface.bastion[0].id,
  ]

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
    name                 = "bastion-osdisk-${var.environment}"
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  admin_ssh_key {
    username = var.admin_username
    # WARNING: If var.ssh_public_key is null, this resource will be destroyed.
    # Ensure secrets.SSH_PUBLIC_KEY is set in GitHub Actions.
    public_key = var.ssh_public_key
  }

  disable_password_authentication = true

  custom_data = base64encode(<<-EOF
              #!/bin/bash
              sudo apt-get update
              sudo apt-get install -y ca-certificates curl apt-transport-https lsb-release gnupg

              # Install Azure CLI
              curl -sL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor | sudo tee /etc/apt/trusted.gpg.d/microsoft.gpg > /dev/null
              AZ_REPO=$(lsb_release -cs)
              echo "deb [arch=amd64] https://packages.microsoft.com/repos/azure-cli/ $AZ_REPO main" | sudo tee /etc/apt/sources.list.d/azure-cli.list
              
              # Install kubectl
              curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
              echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list

              # Install Redis tools & PostgreSQL client
              sudo apt-get update
              sudo apt-get install -y azure-cli kubectl redis-tools postgresql-client
              EOF
  )
}
