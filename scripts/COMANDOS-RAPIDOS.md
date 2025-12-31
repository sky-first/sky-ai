# 🚀 Comandos Rápidos - Deploy Local na VM

## ⚡ Comandos Prontos para Copiar e Colar

### 1. Configurar Variáveis (Execute um por vez)

```bash
export VM_IP=172.191.77.30
```

```bash
export BRANCH=staging
```

```bash
export GH_PAT=ghp_seu_token_aqui
```

**Nota:** Substitua `ghp_seu_token_aqui` pelo seu token real (se repositórios forem privados)

---

### 2. Executar Deploy

```bash
cd sky-poc-infra
./scripts/deploy-local-to-vm.sh
```

---

## 📋 Script Completo (Copie e Cole Tudo)

```bash
export VM_IP=172.191.77.30
export BRANCH=staging
cd sky-poc-infra
./scripts/deploy-local-to-vm.sh
```

**Se repositórios forem privados, adicione antes:**
```bash
export GH_PAT=ghp_seu_token_aqui
```

---

## 🔍 Verificar Variáveis Configuradas

```bash
echo "VM_IP: $VM_IP"
echo "BRANCH: $BRANCH"
echo "GH_PAT: ${GH_PAT:-não configurado}"
```

---

## ❌ Erro: "command not found: #"

**Causa:** Você copiou comandos com comentários inline

**Solução:** Execute os comandos sem os comentários:

**❌ ERRADO:**
```bash
export VM_IP=172.191.77.30  # IP da VM
```

**✅ CORRETO:**
```bash
export VM_IP=172.191.77.30
```

Ou execute linha por linha, sem os comentários.

---

## 📝 Exemplo Completo Passo a Passo

```bash
# 1. Ir para o diretório
cd /Users/thedatafirst/Documents/poc:deploy:sky/sky-poc-infra

# 2. Configurar IP da VM
export VM_IP=172.191.77.30

# 3. Configurar branch (opcional)
export BRANCH=staging

# 4. Se repositórios forem privados, configure token
export GH_PAT=ghp_seu_token_aqui

# 5. Executar deploy
./scripts/deploy-local-to-vm.sh
```

---

## 🆘 Problemas Comuns

### Erro: "VM_IP não definido"
**Solução:**
```bash
export VM_IP=172.191.77.30
```

### Erro: "Chave SSH não encontrada"
**Solução:**
```bash
# Verificar se chave existe
ls -la keys/azure/id_rsa

# Se não existir, criar:
ssh-keygen -t rsa -b 4096 -f keys/azure/id_rsa
```

### Erro: "Não foi possível conectar à VM"
**Solução:**
```bash
# Testar conexão manualmente
ssh -i keys/azure/id_rsa azureuser@172.191.77.30 "echo 'OK'"
```

---

## ✅ Checklist Antes de Executar

- [ ] VM está rodando
- [ ] IP da VM está correto
- [ ] Chave SSH existe: `keys/azure/id_rsa`
- [ ] Arquivo `.env` existe em `sky-poc-infra/`
- [ ] Variável `VM_IP` configurada
- [ ] (Opcional) `GH_PAT` configurado se repositórios forem privados


