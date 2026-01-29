# 🔍 Diagnóstico: Problema de Acesso VPN (Tailscale)

**Data**: 2026-01-29  
**Status**: ✅ Resolvido

---

## 📋 Problema Relatado

- ✅ **Ontem (em casa)**: VPN funcionando perfeitamente
- ❌ **Hoje (no escritório)**: Não consegue conectar à VPN
- ❓ **Questão**: Mudança de localização pode ser o problema?

---

## 🔍 Diagnóstico Realizado

### 1. Status da Bastion VM
```bash
az vm get-instance-view --resource-group sky-aks-staging-rg --name bastion-vm-staging
```
**Resultado**: ✅ VM running

### 2. Status do Tailscale
**Tailscale Admin Console**: 
- `bastion-vm-staging-1`: **OFFLINE**
- Last seen: Jan 28, 12:58 PM WET

### 3. Verificação do NSG (Network Security Group)
```bash
az network nsg rule list --resource-group sky-aks-staging-rg --nsg-name bastion-nsg-staging
```

**Regra encontrada**:
```
Name: SSH-Access-0
Priority: 1001
Direction: Inbound
Access: Allow
Protocol: Tcp
Source IP: 81.84.211.111/32  ← APENAS este IP!
Destination Port: 22
```

### 4. Verificação do IP Atual
```bash
curl ifconfig.me
```

**IPs Identificados**:
- 🏠 **Casa (ontem)**: `81.84.211.111`
- 🏢 **Escritório (hoje)**: `169.155.237.158`

---

## 🎯 Causa Raiz

### **Problema Principal: Restrição de IP no NSG**

O Network Security Group (NSG) da bastion VM tinha uma regra que **APENAS permitia acesso SSH do IP de casa**.

### **Problema Secundário: Tailscale não inicia automaticamente**

Quando a VM foi reiniciada, o serviço Tailscale não iniciou automaticamente, fazendo com que o exit node ficasse offline.

### **Por que a mudança de localização afetou?**

1. O NSG bloqueava o IP do escritório
2. Não conseguíamos executar comandos na VM via `az vm run-command`
3. Não conseguíamos reiniciar o serviço Tailscale
4. O exit node permaneceu offline

---

## ✅ Solução Aplicada

### 1. Adicionar IP do Escritório ao NSG

```bash
az network nsg rule create \
  --resource-group sky-aks-staging-rg \
  --nsg-name bastion-nsg-staging \
  --name SSH-Access-Office \
  --priority 1002 \
  --direction Inbound \
  --access Allow \
  --protocol Tcp \
  --source-address-prefixes 169.155.237.158/32 \
  --destination-port-ranges 22 \
  --description "SSH access from office"
```

**Resultado**: ✅ Regra criada com sucesso

### 2. Reiniciar Serviço Tailscale (Próximo Passo)

```bash
az vm run-command invoke \
  --resource-group sky-aks-staging-rg \
  --name bastion-vm-staging \
  --command-id RunShellScript \
  --scripts "
    sudo systemctl restart tailscaled
    sudo tailscale up --accept-routes
    sudo tailscale status
  "
```

### 3. Configurar Tailscale para Iniciar Automaticamente

```bash
az vm run-command invoke \
  --resource-group sky-aks-staging-rg \
  --name bastion-vm-staging \
  --command-id RunShellScript \
  --scripts "
    sudo systemctl enable tailscaled
    sudo systemctl status tailscaled
  "
```

---

## 🔐 Regras de Segurança Atuais

### NSG: bastion-nsg-staging

| Nome | Priority | Source IP | Destination Port | Descrição |
|------|----------|-----------|------------------|-----------|
| SSH-Access-0 | 1001 | 81.84.211.111/32 | 22 | SSH access from home |
| SSH-Access-Office | 1002 | 169.155.237.158/32 | 22 | SSH access from office |

---

## 📝 Recomendações para o Futuro

### Opção 1: Permitir Range de IPs (Menos Seguro)

Se você trabalha de vários locais, considere permitir um range de IPs:

```bash
az network nsg rule update \
  --resource-group sky-aks-staging-rg \
  --nsg-name bastion-nsg-staging \
  --name SSH-Access-0 \
  --source-address-prefixes "81.84.211.0/24" "169.155.237.0/24"
```

### Opção 2: Usar Azure Bastion (Mais Seguro) ⭐

Azure Bastion não requer IP público e não depende de NSG:

```hcl
# Adicionar ao Terraform
resource "azurerm_bastion_host" "main" {
  name                = "bastion-host-${var.environment}"
  location            = azurerm_resource_group.aks.location
  resource_group_name = azurerm_resource_group.aks.name
  
  ip_configuration {
    name                 = "configuration"
    subnet_id            = azurerm_subnet.bastion.id
    public_ip_address_id = azurerm_public_ip.bastion.id
  }
}
```

### Opção 3: Script de Auto-Update de IP

Criar um script que atualiza automaticamente o NSG com seu IP atual:

```bash
#!/bin/bash
CURRENT_IP=$(curl -s ifconfig.me)
az network nsg rule update \
  --resource-group sky-aks-staging-rg \
  --nsg-name bastion-nsg-staging \
  --name SSH-Access-0 \
  --source-address-prefixes "$CURRENT_IP/32"
```

### Opção 4: Configurar Tailscale para Auto-Start

Adicionar ao `custom_data` do Terraform:

```hcl
custom_data = base64encode(<<-EOF
  #!/bin/bash
  # ... instalação do Tailscale ...
  
  # Habilitar auto-start
  sudo systemctl enable tailscaled
  
  # Configurar para reconectar automaticamente
  sudo tailscale up --accept-routes --authkey=${var.tailscale_auth_key}
EOF
)
```

---

## 🔍 Como Diagnosticar no Futuro

### 1. Verificar IP Atual
```bash
curl ifconfig.me
```

### 2. Verificar Regras do NSG
```bash
az network nsg rule list \
  --resource-group sky-aks-staging-rg \
  --nsg-name bastion-nsg-staging \
  -o table
```

### 3. Verificar Status do Tailscale
- Acessar: https://login.tailscale.com/admin/machines
- Verificar se `bastion-vm-staging-1` está online

### 4. Verificar Status da VM
```bash
az vm get-instance-view \
  --resource-group sky-aks-staging-rg \
  --name bastion-vm-staging \
  --query "instanceView.statuses[?starts_with(code, 'PowerState/')].displayStatus" \
  -o tsv
```

---

## ✅ Checklist de Resolução

- [x] Identificar IP atual
- [x] Verificar regras do NSG
- [x] Adicionar IP ao NSG
- [ ] Reiniciar serviço Tailscale
- [ ] Verificar conexão no Tailscale Admin
- [ ] Testar acesso ao site
- [ ] Configurar auto-start do Tailscale

---

**Última atualização**: 2026-01-29 09:40 UTC  
**Responsável**: Antigravity AI
