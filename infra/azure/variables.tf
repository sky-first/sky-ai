# Este arquivo pode ser usado para definir variáveis com valores padrão
# Ou você pode criar um arquivo terraform.tfvars para sobrescrever valores

variable "resource_group_name" {
  description = "Nome do Resource Group"
  type        = string
  default     = "ai-saas-rg"
}

variable "location" {
  description = "Região do Azure"
  type        = string
  default     = "eastus"
}

variable "vm_name" {
  description = "Nome da VM"
  type        = string
  default     = "ai-saas-vm"
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
}

variable "allowed_postgres_ips" {
  description = "Lista de IPs/CIDRs permitidos para acesso ao PostgreSQL (porta 5433). Se vazio, permite acesso público (protegido por senha do banco)."
  type        = list(string)
  default     = []
  # Exemplo: ["203.0.113.1/32", "203.0.113.2/32"]
  # Nota: Se vazio [], PostgreSQL será público mas protegido por senha
}

variable "frontend_public_access" {
  description = "Se true, permite acesso público ao Frontend (porta 3000). Se false, apenas IPs em allowed_frontend_ips."
  type        = bool
  default     = true
}

variable "allowed_frontend_ips" {
  description = "Lista de IPs/CIDRs permitidos para acesso ao Frontend (porta 3000). Usado apenas se frontend_public_access = false."
  type        = list(string)
  default     = []
}

variable "backend_public_access" {
  description = "Se true, permite acesso público ao Backend (porta 8000). Se false, apenas IPs em allowed_backend_ips."
  type        = bool
  default     = true
}

variable "allowed_backend_ips" {
  description = "Lista de IPs/CIDRs permitidos para acesso ao Backend (porta 8000). Usado apenas se backend_public_access = false."
  type        = list(string)
  default     = []
}

# Variáveis para múltiplos ambientes e CI/CD
variable "environment" {
  description = "Ambiente (staging/prod)"
  type        = string
  validation {
    condition     = contains(["staging", "prod"], var.environment)
    error_message = "Environment deve ser: staging ou prod"
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
