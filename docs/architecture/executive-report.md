# Relatório Executivo de Arquitetura em Nuvem – SkyFirst Platform

**Data:** 24 de Fevereiro de 2026
**Objetivo:** Apresentar a estrutura atual (As-Is) da infraestrutura em nuvem que sustenta a plataforma de Inteligência Artificial da SkyFirst, destacando os fluxos operacionais, níveis de segurança implementados e escalabilidade.
**Público-Alvo:** Diretoria Executiva, Investidores e Liderança de Tecnologia.

---

## 1. Visão Geral da Plataforma (Executivo)

A infraestrutura atual da SkyFirst foi desenhada para suportar fluxos de trabalho intensos de Inteligência Artificial com foco em **Automação**, **Segurança de Identidade** e **Agilidade de Implantação**. Ela opera primariamente sobre o **Microsoft Azure Kubernetes Service (AKS)**, orquestrando um ecossistema que vai desde a interface do usuário até os motores de processamento de IA em *Background*.

A arquitetura vigente balanceia uma entrega rápida de valor para o negócio com a complexidade inerente de um sistema distribuído de alta cardinalidade.

---

## 2. Anatomia da Arquitetura (Os Pilares)

A arquitetura pode ser dividida em cinco camadas principais, fluindo desde o acesso do usuário até o armazenamento persistente de dados:

### 2.1. Borda e Ingresso de Usuários (Acesso Externo)
- **Fluxo do Usuário:** O tráfego origina-se na internet e atinge a plataforma através de um roteamento DNS gerenciado corporativamente.
- **Fronteira de Segurança (NSG + Ingress):** Antes de tocar as aplicações, o tráfego passa por um *Network Security Group (NSG)*, que atua como o porteiro L4, bloqueando conexões não autorizadas.
- **Distribuição de Tráfego:** O Nginx Ingress Controller, residindo dentro do cluster, atua como o roteador inteligente da aplicação, distribuindo requisições entre os serviços de Frontend e Backend baseado na URL acessada.

### 2.2. A Fábrica de Implantação (CI/CD & GitOps)
Nosso modelo operacional difere de arquiteturas legadas pela ausência de intervenção humana na produção.
- **Repositório Central (GitHub):** O código das aplicações e a configuração da infraestrutura (*Infrastructure as Code*) vivem no GitHub.
- **Pipelines Automatizados:** Mudanças acionam pipelines que constroem, testam e empurram imagens de contêineres para o nosso **Azure Container Registry (ACR)** privado.
- **GitOps Bridge:** A implantação no cluster Kubernetes (AKS) é gerenciada de forma declarativa, garantindo que o que está rodando exatamente corresponde ao que foi aprovado no código (auditabilidade 100%).

### 2.3. O Motor Computacional (O Cluster AKS)
Este é o coração da plataforma, orquestrado pela nuvem de forma gerenciada (escalando máquinas automaticamente). O cluster segmenta as responsabilidades através de *Node Pools* dedicados:
- **System Nodes:** Mantêm os serviços essenciais do Kubernetes rodando.
- **Platform Nodes (Frontend/Backend):** Onde as aplicações interativas do usuário final rodam, configuradas com *Auto-Scaling* (HPA) para absorver picos de tráfego web.
- **AI Workers:** Um pool isolado computacionalmente. Aqui, tarefas densas de inferência ou treinamento de modelos de IA operam sem competir por recursos com as aplicações web do usuário final.

### 2.4. A Camada de Identidade Invisível (Zero-Trust)
Este é um dos grandes avanços de segurança desta arquitetura.
- **Azure Key Vault & Entra ID (OIDC):** Nossos serviços (pods) não carregam senhas ou *connection strings* textuais. Em vez disso, utilizamos identidades de workload atreladas ao Microsoft Entra ID para assumir identidades just-in-time e extrair credenciais sigilosas do Azure Key Vault. Se o cluster fosse comprometido, o atacante não acharia um cofre de senhas abertas.

### 2.5. Persistência e Observabilidade (Dados e Estado)
Neste momento de tração inicial da empresa, nossos sistemas de estado rodam dentro da mesma malha elástica de aplicações:
- **Bancos de Dados In-Cluster:** O PostgreSQL (Relacional/Transacional) em formato High Availability (HA) e o Redis (Cache volátil) rodam atualmente como contêineres atrelados a discos provisionados pelo AKS.
- **Torre de Controle (Observabilidade):** Uma suíte de telemetria completa (Prometheus, Grafana e Loki) monitora as entranhas do sistema, enviando métricas processadas e agregadas para o *Azure Log Analytics / Storage Account* para histórico longo.
- **Gestão de Infraestrutura (Terraform):** Toda a espinha dorsal desta malha, desde redes virtuais (VNETs) até a provisão do AKS, é versionada, provisionada e destruída consistentemente através do Terraform (*Azure Storage backend*).

---

## 3. Considerações e Evolução

Esta arquitetura cumpre com êxito o objetivo de suportar a fase atual de validação do produto (Product-Market Fit) com um nível excelente de automação e isolamento lógico. Contudo, como desenhamos infraestruturas com visão de anos à frente, já existem caminhos pavimentados para o próximo salto de maturidade:

1.  **Adoção de Plataforma como Serviço (PaaS) para Dados:** Transferir a responsabilidade da operação e de alta disponibilidade do PostgreSQL e do Redis para os serviços gerenciados nativos da Microsoft (*Azure Database for Postgres/Azure Cache for Redis*), o que aumenta colossalmente o SLA de recuperação contra desastres, reduzindo o esforço da equipe de engenharia.
2.  **Web Application Firewall (WAF):** Inserir inteligência de firewall de aplicação (*Azure Application Gateway*) na frente do tráfego público para inspecionar ameaças lógicas (como SQL Injection ou tráfego malicioso em massa), elevando o nível para conformidade corporativa como SOC 2/ISO 27001 em clientes Enterprise.

**Conclusão:**
A SkyFirst opera uma arquitetura moderna, escalável e amparada nas melhores práticas de integração contínua e governança de identidade, preparada para absorver carga de Inteligência Artificial sem comprometer a agilidade de desenvolvimento da corporação.

---
*Relatório gerado pela Área de Arquitetura de Nuvem / Engenharia.*
