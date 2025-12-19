# Outputs do Terraform
# Valores exportados após o deploy para uso em outros processos

output "vm_id" {
  description = "ID da VM Azure"
  value       = azurerm_linux_virtual_machine.main.id
}

output "vm_public_ip" {
  description = "IP público da VM"
  value       = azurerm_public_ip.main.ip_address
}

output "vm_private_ip" {
  description = "IP privado da VM"
  value       = azurerm_network_interface.main.private_ip_address
}

output "resource_group_name" {
  description = "Nome do Resource Group"
  value       = azurerm_resource_group.main.name
}

output "vm_name" {
  description = "Nome da VM"
  value       = azurerm_linux_virtual_machine.main.name
}

output "environment" {
  description = "Ambiente atual"
  value       = var.environment
}

output "workspace" {
  description = "Workspace Terraform atual"
  value       = terraform.workspace
}

output "deploy_status" {
  description = "Status do deploy (sucesso se health_check foi executado)"
  value       = null_resource.health_check != null ? "success" : "pending"
  depends_on  = [null_resource.health_check]
}

output "ssh_command" {
  description = "Comando SSH para conectar à VM"
  value       = "ssh ${var.admin_username}@${azurerm_public_ip.main.ip_address}"
}

output "git_branch" {
  description = "Branch Git usado no deploy"
  value       = var.git_branch
}
