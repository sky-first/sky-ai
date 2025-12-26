# Este arquivo pode ser usado para definir variáveis com valores padrão
# Ou você pode criar um arquivo terraform.tfvars para sobrescrever valores

variable "check_existing_resources" {
  description = "Se true, valida que recursos não existem antes de criar (evita conflitos)"
  type        = bool
  default     = false
}

variable "resource_group_name" {
  description = "Nome do Resource Group (deve ser único na subscription)"
  type        = string
  validation {
    condition     = length(var.resource_group_name) > 0 && length(var.resource_group_name) <= 90
    error_message = "Resource Group name deve ter entre 1 e 90 caracteres."
  }
}

variable "location" {
  description = "Região do Azure"
  type        = string
  default     = "eastus"
}

variable "vm_name" {
  description = "Nome da VM (deve ser único no Resource Group)"
  type        = string
  validation {
    condition     = length(var.vm_name) > 0 && length(var.vm_name) <= 64
    error_message = "VM name deve ter entre 1 e 64 caracteres."
  }
}

variable "vm_size" {
  description = "Tamanho da VM"
  type        = string
  default     = "Standard_B2s" # 2 vCPUs, 4GB RAM
}

variable "admin_username" {
  description = "Nome de usuário do administrador"
  type        = string
  default     = "azureuser"
}

variable "ssh_public_key" {
  description = "Chave pública SSH (caminho do arquivo ou conteúdo)"
  type        = string
  default     = ""
  sensitive   = false
}

# Variáveis de Segurança - Network Security Group
variable "allowed_ssh_ips" {
  description = "Lista de IPs/CIDRs permitidos para acesso SSH (porta 22). Se vazio, permite acesso público (qualquer IP). Segurança garantida por autenticação via chaves SSH."
  type        = list(string)
  default     = []
  # Exemplo: ["203.0.113.1/32", "203.0.113.2/32", "198.51.100.0/24"]
  # Nota: Se vazio [], SSH será público mas protegido por chaves SSH (sem senha)
  validation {
    condition     = var.environment != "prod" || length(var.allowed_ssh_ips) > 0 || var.enable_bastion
    error_message = "Em produção, allowed_ssh_ips não pode estar vazio a menos que enable_bastion seja true."
  }
}

variable "allowed_postgres_ips" {
  description = "Lista de IPs/CIDRs permitidos para acesso ao PostgreSQL (porta 5433). Se vazio, permite acesso público (protegido por senha do banco)."
  type        = list(string)
  default     = []
  # Exemplo: ["203.0.113.1/32", "203.0.113.2/32"]
  # Nota: Se vazio [], PostgreSQL será público mas protegido por senha
  validation {
    condition     = var.environment != "prod" || length(var.allowed_postgres_ips) > 0
    error_message = "Em produção, allowed_postgres_ips não pode estar vazio."
  }
}

variable "frontend_public_access" {
  description = "Se true, permite acesso público ao Frontend (porta 3000). Se false, apenas IPs em allowed_frontend_ips."
  type        = bool
  default     = false
}

variable "allowed_frontend_ips" {
  description = "Lista de IPs/CIDRs permitidos para acesso ao Frontend (porta 3000). Usado apenas se frontend_public_access = false."
  type        = list(string)
  default     = []
}

variable "backend_public_access" {
  description = "Se true, permite acesso público ao Backend (porta 8000). Se false, apenas IPs em allowed_backend_ips."
  type        = bool
  default     = false
}

variable "allowed_backend_ips" {
  description = "Lista de IPs/CIDRs permitidos para acesso ao Backend (porta 8000). Usado apenas se backend_public_access = false."
  type        = list(string)
  default     = []
}

variable "allowed_http_ips" {
  description = "Lista de IPs/CIDRs permitidos para HTTP (porta 80). Se vazio, porta 80 permanece fechada."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "allowed_https_ips" {
  description = "Lista de IPs/CIDRs permitidos para HTTPS (porta 443). Se vazio, porta 443 permanece fechada."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# Variáveis para múltiplos ambientes e CI/CD
variable "environment" {
  description = "Ambiente (staging/prod/poc-sky)"
  type        = string
  validation {
    condition     = contains(["staging", "prod", "poc-sky"], var.environment)
    error_message = "Environment deve ser: staging, prod ou poc-sky"
  }
}

variable "git_branch" {
  description = "Branch do Git para deploy"
  type        = string
  default     = "main"
}

variable "github_repo" {
  description = "Repositório GitHub (formato: owner/repo)"
  type        = string
  default     = ""
}

variable "subscription_id" {
  description = "ID da subscription Azure (usa ARM_SUBSCRIPTION_ID se não fornecido)"
  type        = string
  sensitive   = true
  default     = ""
}

# Variável para habilitar/desabilitar Azure Bastion
variable "enable_bastion" {
  description = "Se true, cria Azure Bastion para acesso SSH seguro (recomendado para produção). Se false, usa SSH direto via porta 22."
  type        = bool
  default     = true
}

# Variável para email de alertas
variable "alert_email" {
  description = "Email para receber alertas do Azure Monitor (opcional, mas recomendado)"
  type        = string
  default     = ""
  sensitive   = false
}