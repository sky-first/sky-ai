output "resource_group_name" {
  value = azurerm_resource_group.aks.name
}

output "aks_cluster_name" {
  value = azurerm_kubernetes_cluster.aks.name
}

output "aks_cluster_id" {
  value = azurerm_kubernetes_cluster.aks.id
}

output "aks_get_credentials_command" {
  value = "az aks get-credentials --resource-group ${azurerm_resource_group.aks.name} --name ${azurerm_kubernetes_cluster.aks.name}"
}

output "key_vault_name" {
  value = azurerm_key_vault.main.name
}

output "eso_client_id" {
  value = azurerm_user_assigned_identity.eso.client_id
}

output "ingress_ip" {
  value       = "Check Kubernetes Service (kubectl get svc -n ingress-nginx)"
  description = "The Public IP will be allocated by the LoadBalancer service after deployment"
}
