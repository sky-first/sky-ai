# Relatório: O que será necessário no Backend e Frontend

## Data: 26/12/2024

---

## 📋 RESUMO

Este documento descreve o que precisa ser implementado no **Backend (sky-poc-backend)** e **Frontend (sky-poc-frontend)** para completar a funcionalidade de criar dashboards a partir de perguntas favoritadas.

**IMPORTANTE:** A IA já está 100% implementada e funcional. Este relatório é para o desenvolvedor fullstack implementar as integrações necessárias.

---

## 🔄 FLUXO COMPLETO

```
1. Usuário faz pergunta → Recebe resposta
   ↓
2. Usuário clica na ESTRELA → Salvar pergunta/resposta (SEM chamar IA)
   ↓
3. Usuário clica em "Criar Dashboard" → Chamar IA para gerar sugestões
   ↓
4. IA retorna 8 widgets (1 original + 7 relacionadas)
   ↓
5. Backend executa plano e cria dashboard
   ↓
6. Frontend redireciona para dashboard criado
```

**PONTO CRÍTICO:** A IA só é chamada no passo 3, não no passo 2. Isso evita gastos desnecessários de LLM.

---

## 🔧 BACKEND (sky-poc-backend)

### 1. Endpoint para Favoritar Pergunta (se não existir)

**Endpoint:** `POST /api/v1/questions/star` ou similar

**Request Body:**
```json
{
  "question": "Qual foi o total de vendas no último mês?",
  "answer": "O total de vendas foi R$ 50.000,00...",
  "connection_id": "conn-123",
  "space_id": "space-456"
}
```

**Response:**
```json
{
  "id": "starred-question-789",
  "question": "Qual foi o total de vendas no último mês?",
  "answer": "O total de vendas foi R$ 50.000,00...",
  "created_at": "2024-12-26T10:00:00Z"
}
```

**Ação:** Apenas salvar no banco de dados. **NÃO chamar IA aqui.**

### 2. Endpoint para Criar Dashboard a partir de Pergunta Favoritada

**Endpoint:** `POST /api/v1/dashboards/create-from-question`

**Request Body:**
```json
{
  "starred_question_id": "starred-question-789",
  "space_id": "space-456",
  "connection_id": "conn-123"
}
```

**Fluxo Interno:**
1. Buscar pergunta favoritada pelo `starred_question_id`
2. Chamar endpoint do `sky-poc-ai`: `POST /connections/{connection_id}/dashboards/plan`
3. Incluir `original_question` no body da requisição
4. Executar o plano retornado (criar dashboard + widgets)
5. Retornar dashboard criado

**Exemplo de Chamada para sky-poc-ai:**
```python
# No backend, fazer requisição HTTP para sky-poc-ai
response = requests.post(
    f"{AI_SERVICE_URL}/connections/{connection_id}/dashboards/plan",
    json={
        "user_id": current_user.id,
        "space_id": space_id,
        "goal": f"Dashboard baseado na pergunta: {original_question[:50]}...",
        "max_widgets": 8,
        "original_question": original_question,  # ✅ CRÍTICO: passar aqui
        "language": "pt",  # ou detectar do contexto
        "is_personal": is_personal_mode,
    }
)
```

**Response:**
```json
{
  "dashboard_id": "dashboard-123",
  "dashboard_name": "Dashboard de Vendas",
  "widgets_count": 8,
  "created_at": "2024-12-26T10:00:00Z"
}
```

### 3. Integração com Endpoint Existente (Alternativa)

Se já existe endpoint de criação de dashboard, pode ser modificado para aceitar `original_question`:

**Endpoint Existente:** `POST /api/v1/dashboards/ai/build` (ou similar)

**Modificação:**
- Adicionar campo opcional `original_question` no request
- Se fornecido, passar para `sky-poc-ai` no endpoint `/dashboards/plan`
- Se não fornecido, comportamento original mantido

---

## 🎨 FRONTEND (sky-poc-frontend)

### 1. UI da Estrela na Resposta

**Localização:** Componentes que exibem respostas da IA:
- `src/components/dashboard/ai-search-bar.tsx`
- `src/components/dashboard/pipeline-overlay.tsx`
- `src/components/dashboard/widget-container.tsx` (se aplicável)

**Implementação:**
```tsx
// Adicionar botão de estrela ao lado da resposta
<Button
  variant="ghost"
  size="icon"
  onClick={() => handleStarQuestion(question, answer)}
  className={isStarred ? "text-yellow-500" : ""}
>
  <StarIcon className={isStarred ? "fill-current" : ""} />
</Button>
```

**Ação ao Clicar:**
- Chamar `POST /api/v1/questions/star` com `question` e `answer`
- Atualizar estado local (marcar como favoritado)
- **NÃO chamar IA aqui** - apenas salvar

### 2. Modal/Dialog de Criar Dashboard

**Trigger:** Após favoritar, mostrar opção "Criar Dashboard" ou modal com botão

**Componente:**
```tsx
<Dialog open={showCreateDashboard} onOpenChange={setShowCreateDashboard}>
  <DialogContent>
    <DialogHeader>
      <DialogTitle>Criar Dashboard</DialogTitle>
      <DialogDescription>
        Criar um dashboard com esta pergunta e 7 sugestões relacionadas?
      </DialogDescription>
    </DialogHeader>
    
    <div className="space-y-4">
      <div>
        <p className="text-sm font-medium">Pergunta Original:</p>
        <p className="text-sm text-muted-foreground italic">
          {starredQuestion.question}
        </p>
      </div>
      
      <Button
        onClick={handleCreateDashboard}
        disabled={isCreating}
      >
        {isCreating ? "Criando..." : "Criar Dashboard"}
      </Button>
    </div>
  </DialogContent>
</Dialog>
```

### 3. Função de Criar Dashboard

**Implementação:**
```tsx
const handleCreateDashboard = async () => {
  setIsCreating(true);
  try {
    const response = await fetch('/api/v1/dashboards/create-from-question', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        starred_question_id: starredQuestion.id,
        space_id: currentSpace.id,
        connection_id: currentConnection.id,
      }),
    });
    
    const dashboard = await response.json();
    
    // Redirecionar para dashboard criado
    router.push(`/dashboards/${dashboard.dashboard_id}`);
  } catch (error) {
    console.error('Erro ao criar dashboard:', error);
    // Mostrar erro para usuário
  } finally {
    setIsCreating(false);
  }
};
```

### 4. Exibição do Dashboard Criado

O dashboard terá 8 widgets:
- **Widget 1:** Pergunta original do usuário
- **Widgets 2-8:** 7 sugestões relacionadas geradas pela IA

A exibição já deve estar funcionando, pois usa o mesmo sistema de widgets existente.

---

## 📝 ESTRUTURA DE DADOS

### Tabela: `starred_questions` (se não existir)

```sql
CREATE TABLE starred_questions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  connection_id UUID REFERENCES connections(id),
  space_id UUID REFERENCES spaces(id),
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
```

### Modelo Backend (Python)

```python
class StarredQuestion(Base):
    __tablename__ = "starred_questions"
    
    id = Column(UUID, primary_key=True)
    user_id = Column(UUID, ForeignKey("users.id"), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    connection_id = Column(UUID, ForeignKey("connections.id"))
    space_id = Column(UUID, ForeignKey("spaces.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

---

## 🔗 INTEGRAÇÃO COM SKY-POC-AI

### URL do Serviço

Definir variável de ambiente:
```bash
AI_SERVICE_URL=http://localhost:8000  # ou URL do serviço sky-poc-ai
```

### Exemplo Completo de Integração (Python)

```python
import requests
from typing import Optional

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://localhost:8000")

async def create_dashboard_from_question(
    starred_question_id: UUID,
    user_id: UUID,
    space_id: UUID,
    connection_id: UUID,
    is_personal: bool = False,
) -> dict:
    """
    Cria dashboard a partir de pergunta favoritada.
    Chama sky-poc-ai para gerar plano com original_question.
    """
    # 1. Buscar pergunta favoritada
    starred_question = await get_starred_question(starred_question_id, user_id)
    if not starred_question:
        raise NotFoundError("Pergunta favoritada não encontrada")
    
    # 2. Chamar sky-poc-ai para gerar plano
    ai_response = requests.post(
        f"{AI_SERVICE_URL}/connections/{connection_id}/dashboards/plan",
        json={
            "user_id": str(user_id),
            "space_id": str(space_id),
            "goal": f"Dashboard: {starred_question.question[:50]}...",
            "max_widgets": 8,
            "original_question": starred_question.question,  # ✅ CRÍTICO
            "language": "pt",  # ou detectar
            "is_personal": is_personal,
        },
        timeout=30,
    )
    ai_response.raise_for_status()
    plan = ai_response.json()
    
    # 3. Executar plano (criar dashboard + widgets)
    dashboard = await create_dashboard_from_plan(
        plan=plan,
        user_id=user_id,
        space_id=space_id,
        connection_id=connection_id,
    )
    
    return dashboard
```

---

## ✅ CHECKLIST DE IMPLEMENTAÇÃO

### Backend:
- [ ] Criar endpoint `POST /api/v1/questions/star` (se não existir)
- [ ] Criar tabela/modelo `starred_questions` (se não existir)
- [ ] Criar endpoint `POST /api/v1/dashboards/create-from-question`
- [ ] Implementar integração com `sky-poc-ai` (chamar `/dashboards/plan` com `original_question`)
- [ ] Adicionar variável de ambiente `AI_SERVICE_URL`
- [ ] Testar fluxo completo

### Frontend:
- [ ] Adicionar botão de estrela na resposta da IA
- [ ] Implementar função de favoritar (chamar endpoint do backend)
- [ ] Criar modal/dialog "Criar Dashboard"
- [ ] Implementar função de criar dashboard (chamar endpoint do backend)
- [ ] Adicionar loading states
- [ ] Adicionar tratamento de erros
- [ ] Testar fluxo completo

---

## 🧪 TESTES RECOMENDADOS

### Backend:
1. Testar favoritar pergunta (salvar sem chamar IA)
2. Testar criar dashboard (chamar IA com `original_question`)
3. Verificar que primeira widget é a pergunta original
4. Verificar que outras 7 são relacionadas
5. Testar tratamento de erros

### Frontend:
1. Testar UI da estrela (favoritar/desfavoritar)
2. Testar modal de criar dashboard
3. Testar criação de dashboard (loading, sucesso, erro)
4. Testar redirecionamento para dashboard criado
5. Testar em diferentes componentes (AISearchBar, PipelineOverlay, etc.)

---

## 📚 DOCUMENTAÇÃO DA API

### Endpoint Backend: `POST /api/v1/dashboards/create-from-question`

**Request:**
```json
{
  "starred_question_id": "uuid",
  "space_id": "uuid",
  "connection_id": "uuid"
}
```

**Response:**
```json
{
  "dashboard_id": "uuid",
  "dashboard_name": "string",
  "widgets_count": 8,
  "created_at": "ISO8601"
}
```

---

## ⚠️ OBSERVAÇÕES IMPORTANTES

1. **Economia de LLM:** A IA só é chamada ao criar dashboard, não ao favoritar
2. **Campo `original_question`:** Deve ser passado para `sky-poc-ai` no endpoint `/dashboards/plan`
3. **Primeira Widget:** Sempre será a pergunta original (garantido pela IA)
4. **Widgets 2-8:** 7 sugestões relacionadas geradas pela IA (70-80% de peso)
5. **Compatibilidade:** Se `original_question` não for fornecida, comportamento original é mantido

---

## 🎉 CONCLUSÃO

A IA está 100% implementada e pronta. O backend e frontend precisam apenas:

1. **Backend:** Criar endpoints e integrar com `sky-poc-ai` passando `original_question`
2. **Frontend:** Adicionar UI da estrela e modal de criar dashboard

A integração é simples: apenas passar `original_question` no body da requisição para `sky-poc-ai`.

