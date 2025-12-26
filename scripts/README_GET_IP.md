# Como Descobrir seu IP Público

Este guia mostra diferentes formas de descobrir seu IP público para configurar o acesso SSH.

## 🚀 Métodos Rápidos

### Windows (PowerShell)

**Se der erro de política de execução, use:**
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\get_my_ip.ps1
```

**Ou comando direto (mais simples):**
```powershell
(Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing).Content
```

**Ou script batch:**
```cmd
.\scripts\get_my_ip_cmd.bat
```

### Linux/Mac

```bash
./scripts/get_my_ip.sh
```

**Ou comando direto:**
```bash
curl https://api.ipify.org
```

### Via Navegador

Acesse: **https://api.ipify.org**

## 📝 Exemplo de Uso

1. **Descobrir IP:**
   ```powershell
   (Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing).Content
   ```
   Resultado: `81.84.211.111`

2. **Adicionar ao terraform.tfvars.prod:**
   ```hcl
   allowed_ssh_ips = ["81.84.211.111/32"]
   ```

3. **Aplicar:**
   ```bash
   cd infra/azure
   terraform apply -var-file=terraform.tfvars.prod
   ```

## ⚠️ Problemas Comuns

### Erro: "running scripts is disabled"

**Solução:** Use o comando direto ou bypass:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\get_my_ip.ps1
```

### Erro: "Não foi possível descobrir IP"

**Soluções:**
1. Verifique sua conexão com internet
2. Tente outro serviço: `https://ifconfig.me/ip`
3. Use o navegador: https://api.ipify.org

### IP mudou

Se seu IP mudar (ex: internet residencial), você precisará:
1. Descobrir o novo IP
2. Atualizar `terraform.tfvars.prod`
3. Aplicar: `terraform apply`

## 🔗 Serviços Alternativos

Se um serviço não funcionar, tente:
- https://api.ipify.org
- https://ifconfig.me/ip
- https://icanhazip.com
- https://checkip.amazonaws.com

