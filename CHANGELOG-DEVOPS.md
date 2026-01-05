# Changelog - Melhorias DevOps

## [2026-01-02] - Centralização de Configuração

### 🎯 Objetivo
Implementar abordagem DevOps de **Single Source of Truth** para configurações, centralizando todas as URLs e caminhos no repositório de infraestrutura.

### ✅ Mudanças Implementadas

#### 1. Atualização do `env.example`
- ✅ Atualizado IP de exemplo de `172.191.77.30` para `20.86.142.1` (IP atual da VM POC-SKY)
- ✅ Adicionada documentação sobre path relativo vs URL completa
- ✅ Melhorada documentação sobre quando usar cada abordagem
- ✅ Adicionadas notas sobre atualização automática via scripts

#### 2. Script `fix-next-public-api-url.sh` (NOVO)
- ✅ Detecta problemas comuns (localhost:8000, IP desatualizado)
- ✅ Corrige automaticamente preferindo path relativo
- ✅ Suporta ambos os modos (path relativo ou IP completo)
- ✅ Fornece feedback claro sobre correções aplicadas

#### 3. Melhorias no `ensure-complete-env.sh`
- ✅ Melhorada lógica de detecção de problemas
- ✅ Preferência por path relativo (`/api/v1`) quando possível
- ✅ Detecção e correção automática de `localhost:8000`
- ✅ Validação de IP desatualizado
- ✅ Mensagens de log mais claras

#### 4. Script `diagnose-frontend-backend-error.sh` (NOVO)
- ✅ Diagnóstico específico para erro "Failed to load data"
- ✅ Verifica containers Docker
- ✅ Valida `NEXT_PUBLIC_API_URL`
- ✅ Testa conectividade backend
- ✅ Verifica configuração CORS
- ✅ Analisa logs do frontend
- ✅ Aplica correções automáticas quando possível

#### 5. Documentação Completa
- ✅ Criado `docs/DEVOPS-CONFIGURACAO-CENTRALIZADA.md`
- ✅ Documentação de princípios e práticas
- ✅ Guia de resolução de problemas
- ✅ Checklist de validação
- ✅ Referências e boas práticas

### 🔧 Arquivos Modificados

1. `env.example` - Atualizado com IP correto e melhor documentação
2. `scripts/azure/ensure-complete-env.sh` - Melhorada lógica de configuração
3. `scripts/azure/fix-next-public-api-url.sh` - NOVO
4. `scripts/azure/diagnose-frontend-backend-error.sh` - NOVO
5. `docs/DEVOPS-CONFIGURACAO-CENTRALIZADA.md` - NOVO

### 🎯 Benefícios

1. **Single Source of Truth**: Todas as configurações centralizadas
2. **Correção Automática**: Scripts detectam e corrigem problemas comuns
3. **Melhor Diagnóstico**: Script específico para erro do frontend
4. **Documentação Completa**: Guia claro para equipe
5. **Manutenibilidade**: Fácil atualizar IPs e configurações

### 🚀 Como Usar

#### Corrigir NEXT_PUBLIC_API_URL
```bash
./scripts/azure/fix-next-public-api-url.sh
```

#### Diagnosticar Erro do Frontend
```bash
./scripts/azure/diagnose-frontend-backend-error.sh
```

#### Garantir .env Completo
```bash
./scripts/azure/ensure-complete-env.sh
```

### 📝 Próximos Passos Recomendados

1. Testar scripts na VM de produção
2. Integrar scripts no pipeline de deploy
3. Adicionar validação no CI/CD
4. Treinar equipe na nova abordagem

---

**Autor**: Equipe DevOps  
**Data**: 2026-01-02

