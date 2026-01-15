moved {
  from = azurerm_resource_group.main
  to   = azurerm_resource_group.aks
}

moved {
  from = azurerm_virtual_network.main
  to   = azurerm_virtual_network.aks
}

moved {
  from = azurerm_subnet.main
  to   = azurerm_subnet.aks
}

moved {
  from = azurerm_public_ip.main
  to   = azurerm_public_ip.bastion
}

moved {
  from = azurerm_network_security_group.main
  to   = azurerm_network_security_group.bastion
}

moved {
  from = azurerm_network_interface.main
  to   = azurerm_network_interface.bastion
}

moved {
  from = azurerm_linux_virtual_machine.main
  to   = azurerm_linux_virtual_machine.bastion
}
