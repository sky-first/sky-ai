# Chaves SSH - Azure

Este diretório contém as chaves SSH para acesso às VMs do Azure.

## Estrutura

- `id_rsa.pub` - Chave pública SSH (pode ser commitada)
- `id_rsa` - Chave privada SSH (NÃO deve ser commitada - está no .gitignore)

## Uso

A chave pública é referenciada no Terraform através do arquivo `terraform.tfvars`:

```hcl
ssh_public_key = file("${path.module}/../../keys/azure/id_rsa.pub")
```

## Segurança

 **IMPORTANTE**: A chave privada (`id_rsa`) nunca deve ser commitada no repositório.

Se você precisar gerar uma nova chave:

```bash
ssh-keygen -t rsa -b 4096 -C "seu-email@exemplo.com" -f keys/azure/id_rsa
```
