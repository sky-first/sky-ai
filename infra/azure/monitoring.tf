# Azure Monitor - Monitoramento e Alertas
# CRÍTICO: Implementação de observabilidade básica

# Action Group para notificações
resource "azurerm_monitor_action_group" "main" {
  name                = "ai-saas-alerts-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  short_name          = "ai-saas"

  # Email notification (adicione outros canais conforme necessário)
  # Para produção, configure: email, SMS, webhook, etc.
  dynamic "email_receiver" {
    for_each = var.alert_email != "" ? [1] : []
    content {
      name          = "devops-team"
      email_address = var.alert_email
    }
  }

  tags = {
    Environment = var.environment
    Project     = "AI-SaaS"
    Workspace   = terraform.workspace
  }
}

# Alert: CPU alta na VM
resource "azurerm_monitor_metric_alert" "vm_cpu_high" {
  name                = "ai-saas-vm-cpu-high-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_linux_virtual_machine.main.id]
  description         = "Alerta quando CPU da VM excede 80%"
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"

  criteria {
    metric_namespace = "Microsoft.Compute/virtualMachines"
    metric_name      = "Percentage CPU"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = 80
  }

  action {
    action_group_id = azurerm_monitor_action_group.main.id
  }

  tags = {
    Environment = var.environment
    Project     = "AI-SaaS"
  }
}

# Alert: Memória alta na VM
resource "azurerm_monitor_metric_alert" "vm_memory_high" {
  name                = "ai-saas-vm-memory-high-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_linux_virtual_machine.main.id]
  description         = "Alerta quando memória disponível da VM é menor que 500MB"
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"

  criteria {
    metric_namespace = "Microsoft.Compute/virtualMachines"
    metric_name      = "Available Memory Bytes"
    aggregation      = "Average"
    operator         = "LessThan"
    threshold        = 524288000  # 500MB em bytes
  }

  action {
    action_group_id = azurerm_monitor_action_group.main.id
  }

  tags = {
    Environment = var.environment
    Project     = "AI-SaaS"
  }
}

# Alert: Disco quase cheio
resource "azurerm_monitor_metric_alert" "vm_disk_high" {
  name                = "ai-saas-vm-disk-high-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_linux_virtual_machine.main.id]
  description         = "Alerta quando espaço em disco é menor que 5GB"
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"

  criteria {
    metric_namespace = "Microsoft.Compute/virtualMachines"
    metric_name      = "OS Disk Free Space"
    aggregation      = "Average"
    operator         = "LessThan"
    threshold        = 5368709120  # 5GB em bytes
  }

  action {
    action_group_id = azurerm_monitor_action_group.main.id
  }

  tags = {
    Environment = var.environment
    Project     = "AI-SaaS"
  }
}

# Alert: VM não disponível (status check failed)
resource "azurerm_monitor_metric_alert" "vm_unavailable" {
  name                = "ai-saas-vm-unavailable-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_linux_virtual_machine.main.id]
  description         = "Alerta quando VM não está respondendo (status check failed)"
  severity            = 0  # Critical
  frequency           = "PT1M"
  window_size         = "PT5M"

  criteria {
    metric_namespace = "Microsoft.Compute/virtualMachines"
    metric_name      = "VM Availability"
    aggregation      = "Average"
    operator         = "LessThan"
    threshold        = 1
  }

  action {
    action_group_id = azurerm_monitor_action_group.main.id
  }

  tags = {
    Environment = var.environment
    Project     = "AI-SaaS"
  }
}

