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
  value       = length(null_resource.health_check) > 0 ? "success" : "pending"
  depends_on  = [null_resource.health_check]
}

output "ssh_command" {
  description = "Comando SSH para conectar à VM (legado - use Bastion se habilitado)"
  # CRÍTICO: evitar "Invalid index" quando Bastion ainda não existe no state/plan
  value = var.enable_bastion ? try(
    "Use Azure Bastion via Portal ou: az network bastion ssh --name ${azurerm_bastion_host.main[0].name} --resource-group ${azurerm_resource_group.main.name} --target-resource-id ${azurerm_linux_virtual_machine.main.id} --auth-type ssh --username ${var.admin_username}",
    "Use Azure Bastion via Portal (Bastion ainda não está disponível no state/plan)."
  ) : "ssh ${var.admin_username}@${azurerm_public_ip.main.ip_address}"
}

output "bastion_host_id" {
  description = "ID do Azure Bastion Host (se habilitado)"
  value       = var.enable_bastion ? try(azurerm_bastion_host.main[0].id, null) : null
}

output "bastion_host_name" {
  description = "Nome do Azure Bastion Host (se habilitado)"
  value       = var.enable_bastion ? try(azurerm_bastion_host.main[0].name, null) : null
}

output "git_branch" {
  description = "Branch Git usado no deploy"
  value       = var.git_branch
}

output "monitoring_action_group_id" {
  description = "ID do Action Group para alertas"
  value       = azurerm_monitor_action_group.main.id
}
