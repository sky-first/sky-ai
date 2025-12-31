# 🚀 Comandos Simples para Deploy

## ⚡ Forma Mais Simples (Copie e Cole)

```bash
export VM_IP=172.191.77.30
export BRANCH=staging
export SSH_KEY=~/Documents/poc:deploy:sky/sky-poc-infra/keys/azure/team/id_rsa_poc
cd ~/Documents/poc:deploy:sky/sky-poc-infra
./scripts/deploy-local-to-vm.sh
```

---

## 🔑 Opções de Chave SSH

### Opção 1: Chave POC (Recomendado)
```bash
export SSH_KEY=~/Documents/poc:deploy:sky/sky-poc-infra/keys/azure/team/id_rsa_poc
```

### Opção 2: Chave SSH do Sistema
```bash
export SSH_KEY=~/.ssh/id_ed25519
```

### Opção 3: Chave SSH RSA do Sistema
```bash
export SSH_KEY=~/.ssh/id_rsa
```

---

## 📋 Script Completo (Uma Linha)

```bash
export VM_IP=172.191.77.30 && export BRANCH=staging && export SSH_KEY=~/Documents/poc:deploy:sky/sky-poc-infra/keys/azure/team/id_rsa_poc && cd ~/Documents/poc:deploy:sky/sky-poc-infra && ./scripts/deploy-local-to-vm.sh
```

---

## ✅ Verificar Chave SSH

```bash
ls -la ~/Documents/poc:deploy:sky/sky-poc-infra/keys/azure/team/id_rsa_poc
```

Se existir, use essa chave. Se não, use a chave do sistema.

---

## 🆘 Se Ainda Der Erro

Execute um por vez:

```bash
export VM_IP=172.191.77.30
```

```bash
export BRANCH=staging
```

```bash
export SSH_KEY=~/Documents/poc:deploy:sky/sky-poc-infra/keys/azure/team/id_rsa_poc
```

```bash
cd ~/Documents/poc:deploy:sky/sky-poc-infra
```

```bash
./scripts/deploy-local-to-vm.sh
```


