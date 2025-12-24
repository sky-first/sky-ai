# Infraestrutura Azure - AI SaaS

Este diretório contém a configuração Terraform para criar a infraestrutura no Azure.

## Pré-requisitos

1. **Azure CLI instalado e configurado**
   ```bash
   brew install azure-cli
   az login
   ```

2. **Terraform instalado**
   ```bash
   brew install terraform
   ```

3. **Chave SSH pública** (para autenticação na VM)
   ```bash
   # Gerar nova chave se necessário
   ssh-keygen -t rsa -b 4096 -C "seu-email@exemplo.com" (chave gerada cd infra/azure)

   ```

## Configuração Inicial

### 1. Fazer login no Azure

```bash
az login
```

Isso abrirá seu navegador para autenticação. Após o login, você verá suas assinaturas.

### 2. Definir assinatura padrão (se tiver múltiplas)

```bash
# Listar assinaturas
az account list --output table

# Definir assinatura padrão
az account set --subscription "nome-ou-id-da-assinatura"
```

### 3. Configurar variáveis do Terraform

```bash
cd infra/azure
cp terraform.tfvars.example terraform.tfvars
```

Edite o arquivo `terraform.tfvars` e configure:

```hcl
resource_group_name = "ai-saas-rg"
location            = "eastus"  # ou "brazilsouth" para Brasil
vm_name             = "ai-saas-vm"
vm_size             = "Standard_B2s"
admin_username      = "azureuser"

# Caminho para sua chave pública SSH
ssh_public_key = file("~/.ssh/id_rsa.pub")

# SSH está configurado para acesso público com autenticação por chaves SSH
# Quando você compartilhar a chave SSH com o time, eles podem acessar de qualquer lugar
# Veja a seção "Segurança e Acesso ao Servidor" abaixo para mais detalhes
```

## Criar Infraestrutura

### 1. Inicializar Terraform

```bash
cd infra/azure
terraform init
```

### 2. Verificar o plano de execução

```bash
terraform plan
```

Isso mostrará todos os recursos que serão criados:
- Resource Group
- Virtual Network e Subnet
- Public IP
- Network Security Group (Firewall)
- Network Interface
- Virtual Machine (Ubuntu 22.04 LTS)

### 3. Aplicar a configuração

```bash
terraform apply
```

Digite `yes` quando solicitado. Isso criará todos os recursos no Azure.

### 4. Obter informações da VM

Após a criação, você verá os outputs:
- `vm_public_ip`: IP público da VM
- `vm_private_ip`: IP privado da VM
- `vm_id`: ID da VM
- `ssh_command`: Comando SSH para conectar

Para ver novamente:
```bash
terraform output
```

## Acessar a VM

### Método 1: Script automatizado (Recomendado)

```bash
# Do diretório raiz do projeto
./access_server_azure.sh
```

### Método 2: SSH manual

```bash
# Obter IP público
cd infra/azure
PUBLIC_IP=$(terraform output -raw vm_public_ip)

# Conectar
ssh azureuser@$PUBLIC_IP
```

### Método 3: Via Azure CLI

```bash
az vm run-command invoke \
  -g ai-saas-rg \
  -n ai-saas-vm \
  --command-id RunShellScript \
  --scripts "echo 'Hello from Azure VM'"
```

## Recursos Criados

| Recurso | Nome | Descrição |
|---------|------|-----------|
| Resource Group | `ai-saas-rg` | Grupo de recursos que contém tudo |
| Virtual Network | `ai-saas-vnet` | Rede virtual (10.0.0.0/16) |
| Subnet | `ai-saas-subnet` | Sub-rede (10.0.1.0/24) |
| Public IP | `ai-saas-public-ip` | IP público estático |
| Network Security Group | `ai-saas-nsg` | Firewall com regras para SSH, Frontend, Backend e PostgreSQL |
| Network Interface | `ai-saas-nic` | Interface de rede da VM |
| Virtual Machine | `ai-saas-vm` | VM Ubuntu 22.04 LTS (Standard_B2s) |

## Segurança e Acesso ao Servidor

### Acesso via Chaves SSH (Recomendado)

O servidor está configurado para **acesso público via SSH** com autenticação forte por chaves SSH. Isso significa:

-  **Qualquer pessoa com a chave SSH pode acessar de qualquer lugar**
-  **Não precisa configurar IPs manualmente**
-  **Segurança garantida**: apenas chaves SSH (sem senha)
-  **Fácil de compartilhar**: basta passar a chave SSH para o time

#### Como Funciona

1. **Você gera/configura a chave SSH** no `terraform.tfvars`
2. **A chave é adicionada à VM** durante a criação
3. **Você compartilha a chave privada** com o time
4. **Eles acessam de qualquer lugar** usando a chave

#### Compartilhar Acesso com o Time

```bash
# 1. A chave privada está em:
keys/azure/id_rsa

# 2. Compartilhe essa chave de forma segura com o time
# (use um gerenciador de senhas ou canal seguro)

# 3. Eles usam o script de acesso:
./access_server_azure.sh

# Ou manualmente:
ssh -i keys/azure/id_rsa azureuser@<IP_PUBLICO_DA_VM>
```

### Regras de Firewall (Network Security Group)

| Porta | Protocolo | Acesso padrão | Como liberar |
|-------|-----------|---------------|--------------|
| 22 | TCP | Fechada (sem regra) | Adicione IPs em `allowed_ssh_ips` |
| 80 | TCP | Aberta (0.0.0.0/0) | Ajuste `allowed_http_ips` se quiser restringir |
| 443 | TCP | Aberta (0.0.0.0/0) | Ajuste `allowed_https_ips` se quiser restringir |
| 3000 | TCP | Fechada (public_access = false) | Defina `frontend_public_access=true` **ou** IPs em `allowed_frontend_ips` |
| 8000 | TCP | Fechada (public_access = false) | Defina `backend_public_access=true` **ou** IPs em `allowed_backend_ips` |
| 5433 | TCP | Fechada (sem regra) | Adicione IPs em `allowed_postgres_ips` |

### Segurança Implementada

- **SSH**: Autenticação apenas por chaves SSH (senha desabilitada); sem regra se você não preencher `allowed_ssh_ips`.
- **PostgreSQL**: Porta fechada por padrão; só abre para a lista em `allowed_postgres_ips`.
- **Frontend/Backend**: Fechados por padrão; abra explicitamente por IP ou marque `public_access=true` se for realmente necessário.
- **Proxy (HTTP/HTTPS)**: 80/443 abertos por padrão; restrinja com `allowed_http_ips`/`allowed_https_ips` se precisar.
- **VM**: Ubuntu 22.04 LTS com atualizações de segurança

### Abrir acesso por IP (recomendado)

1. Edite `terraform.tfvars` e substitua os placeholders por seus IPs /32:
   ```hcl
   allowed_ssh_ips = [
     "203.0.113.10/32", # Seu IP
   ]
   allowed_postgres_ips = [
     "203.0.113.10/32", # IPs autorizados ao banco
   ]
   allowed_frontend_ips = [
     "203.0.113.10/32",
   ]
   allowed_backend_ips = [
     "203.0.113.10/32",
   ]
   ```

2. Se precisar de acesso público temporário a frontend/backend, mude para `frontend_public_access = true` ou `backend_public_access = true` e replaneje.

3. Aplique as mudanças:
   ```bash
   terraform apply
   ```

### Verificar Regras Ativas

```bash
# Listar todas as regras do NSG
az network nsg rule list \
  -g ai-saas-rg \
  --nsg-name ai-saas-nsg \
  --output table
```

### Gerenciar VM

```bash
# Parar VM (mantém recursos, mas não cobra por horas de computação)
az vm deallocate -g ai-saas-rg -n ai-saas-vm

# Iniciar VM
az vm start -g ai-saas-rg -n ai-saas-vm

# Reiniciar VM
az vm restart -g ai-saas-rg -n ai-saas-vm

# Ver status
az vm show -g ai-saas-rg -n ai-saas-vm -d --query "powerState" -o tsv
```

### Ver informações

```bash
# Listar VMs no Resource Group
az vm list -g ai-saas-rg -o table

# Ver IP público
az vm show -d -g ai-saas-rg -n ai-saas-vm --query publicIps -o tsv

# Ver todos os recursos
az resource list -g ai-saas-rg -o table
```

### Terraform

```bash
# Ver estado atual
terraform show

# Ver outputs
terraform output

# Destruir tudo (CUIDADO!)
terraform destroy
```

## Atualizar Infraestrutura

Após fazer mudanças no `main.tf`:

```bash
terraform plan    # Ver o que será alterado
terraform apply   # Aplicar mudanças
```

## Destruir Infraestrutura

 **ATENÇÃO**: Isso deletará TODOS os recursos criados!

```bash
terraform destroy
```

## Notas

- A VM usa **Ubuntu 22.04 LTS** (equivalente à AMI usada na AWS)
- O tamanho **Standard_B2s** é equivalente ao **t3.medium** da AWS
- O disco do sistema é **Premium_LRS** (SSD) com **30GB**
- A autenticação SSH por senha está **desabilitada** por padrão (mais seguro)
- O IP público é **estático**, então não mudará ao reiniciar a VM

## Troubleshooting

### Erro: "Resource group already exists"
- Use um nome diferente ou delete o Resource Group existente:
  ```bash
  az group delete -n ai-saas-rg --yes
  ```

### Erro: "SSH key not found"
- Verifique se o caminho da chave está correto no `terraform.tfvars`
- Ou gere uma nova chave: `ssh-keygen -t rsa -b 4096`

### Não consigo conectar via SSH
- Verifique se a VM está rodando: `az vm show -d -g ai-saas-rg -n ai-saas-vm`
- Verifique o NSG: `az network nsg rule list -g ai-saas-rg --nsg-name ai-saas-nsg`
- Verifique o IP público: `terraform output vm_public_ip`

### VM não inicia
- Verifique os logs: `az vm get-instance-view -g ai-saas-rg -n ai-saas-vm`
- Verifique o boot diagnostics: `az vm boot-diagnostics get-boot-log -g ai-saas-rg -n ai-saas-vm`

## Referências

- [Documentação Azure Terraform Provider](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs)
- [Azure CLI Reference](https://docs.microsoft.com/cli/azure/)
- [Azure VM Sizes](https://docs.microsoft.com/azure/virtual-machines/sizes)
