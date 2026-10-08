# A indexação está a matar o serviço de IA — o que fazer

> Escrito a 02/09/2026, depois de o `sky-ai` ter sido morto por falta de
> memória duas vezes em duas horas, em produção. **Nenhuma linha de código
> foi alterada antes deste documento existir.**

---

## 1. O que aconteceu

O teste das 20 perguntas correu em produção pela primeira vez desde Maio.
Nas duas passagens, o pod do `sky-ai` foi morto a meio:

```
razao=OOMKilled  codigo=137  quando=2026-09-02T18:18:39Z
razao=OOMKilled  codigo=137  quando=2026-09-02T20:10:52Z
```

Cada morte levou consigo as perguntas em curso — o cliente vê
`ConnectError`, e como **só existe uma réplica**, é a app em baixo para
toda a gente enquanto o pod reinicia.

Na primeira passagem havia uma explicação inocente: o teste forçava a
reindexação das cinco ligações a cada corrida. Isso foi corrigido
(sky-backend #690) e verificou-se: quatro das cinco passaram a ser
saltadas em 17 ms.

**E o pod morreu na mesma.** Portanto não era o teste.

## 2. Onde vai a memória

| | |
|---|---|
| pod em repouso | **195 MiB** |
| limite configurado | 5 GiB |
| nós | 5 × `t3.large` — 8 GB, **6,9 GiB alocáveis** |
| já reservado no nó do `sky-ai` | 5,2 GiB (73%) |

195 MiB em repouso contra um limite de 5 GiB: o consumo é todo
transitório. Vem de uma coisa concreta — o modelo de indexação
`intfloat/multilingual-e5-large`, que corre **dentro do processo** e ocupa
~2,5 GiB residentes assim que é carregado.

O carregamento é preguiçoso: acontece no primeiro `embed()`. Ou seja,
basta **uma** ligação ser indexada para o pod passar de 195 MiB para uns
2,7 GiB, e ficar assim. As perguntas seguintes acumulam por cima até
rebentar o limite.

Foi exactamente esta a sequência da segunda passagem: quatro ligações
saltadas, uma indexada (`Product Usage`, 1123 ms), e a morte 4 minutos
depois, já a meio das perguntas.

### Porque é que 5 GiB não chega — e 6 também não chegaria

O nó tem 6,9 GiB alocáveis e já tem 5,2 GiB de *requests* comprometidos.
Se o `sky-ai` usar os 5 GiB a que tem direito, a soma com os vizinhos
passa dos 6,9 GiB do nó e o kubelet começa a despejar pods.

**Um serviço que precisa de ~5 GiB não cabe com folga num nó de 7 GiB.**
Subir o limite para 6 não resolve — muda apenas quem morre.

## 3. Os caminhos, com o que foi medido

| caminho | memória residente | qualidade PT↔EN | custo recorrente | estado |
|---|---|---|---|---|
| local `multilingual-e5-large` (hoje) | ~2,5 GiB | **0,917** | zero | mata o pod |
| local `mxbai-embed-large-v1` | **~0,64 GiB** | 0,549 | zero | disponível já |
| Bedrock `titan-embed-text-v2` | ~zero | — | por chamada | **inutilizável** |
| OpenAI verdadeiro | ~zero | — | por chamada | exige conta nova |
| nós maiores (`t3.xlarge`) | — | 0,917 | **dobro do nó** | disponível já |
| indexação fora do pod de serviço | ~zero **no serviço** | 0,917 | zero | exige trabalho |

Os números de qualidade estão medidos e comentados em
`core/rag/embeddings.py`: similaridade do cosseno entre a mesma pergunta
em PT e EN, média de 3 pares. Quanto mais alto, melhor a pesquisa
cruzada entre línguas.

### O que se verificou sobre o Bedrock

O comentário em `core/llm/factory.py` diz que o provider local existe
*«porque a inferência on-demand do Bedrock está bloqueada ao nível da
conta»*. Isso foi verificado hoje e **continua verdade na prática**:

```
$ aws bedrock get-foundation-model-availability --model-id amazon.titan-embed-text-v2:0
  agreementAvailability: AVAILABLE
  authorizationStatus:   AUTHORIZED
  entitlementAvailability: AVAILABLE
```

A metadata diz que está tudo autorizado. Mas **todas as invocações
falham**, tanto com o perfil de operador como de dentro do pod, com a
identidade IRSA que ele usa:

```
ThrottlingException: Too many requests, please wait before trying again
  (reached max retries: 4)
```

Não é ruído de um pico: 4 tentativas espaçadas, das duas origens, todas
recusadas. **Não é um caminho que se possa escolher hoje.**

### E o que se pensava ser o caminho óbvio

`AI_PROVIDER=openai` **não aponta para o OpenAI.** Aponta para
`bedrock-mantle.eu-west-1.api.aws/v1` — um serviço da AWS que fala o
mesmo protocolo. E, como o comentário do código já avisava, **o mantle
não serve modelos de indexação.**

Portanto «já pagamos ao OpenAI, passe-se a indexação para lá» não é uma
opção: não há lá para onde passar. Usar OpenAI a sério significa abrir
conta, gerar chave e assumir orçamento novo.

## 4. A escala da migração é pequena

Qualquer mudança de modelo obriga a reindexar, porque vectores de
modelos diferentes **têm a mesma largura mas vivem em espaços
diferentes** — misturá-los degrada a pesquisa em silêncio, sem erro
nenhum. Contado em produção:

| base | `embeddings` | `semantic_cache` | `knowledge_file_chunks` |
|---|---|---|---|
| plataforma | 11 | 0 | 0 |
| cliente `sandbox` | 29 | 0 | 0 |

**40 vectores ao todo.** Reindexar é uma chamada a `/discover` por
ligação — segundos, não um projecto.

E **não há migração de esquema**: todos os modelos em cima dão 1024
dimensões, que é o que a coluna `Vector(EMBEDDING_DIM)` espera.

## 5. Recomendação

**Tirar a indexação do pod que serve os pedidos.**

O modelo só é preciso quando se liga ou refresca uma fonte de dados —
uma operação rara e assíncrona. Não tem de viver no processo que responde
às perguntas dos utilizadores.

Passando-o para um Job ou worker próprio:

- o serviço que os utilizadores usam volta a ser um processo de ~200 MiB,
  e deixa de poder ser morto por causa de indexação;
- mantém-se a qualidade 0,917, que é o melhor número medido;
- não há custo recorrente nenhum;
- os nós actuais passam a chegar e sobrar.

É o único caminho que não troca uma coisa por outra. Custa trabalho de
engenharia — não é uma variável de ambiente.

### Se for preciso parar a sangria já

`LOCAL_EMBEDDING_MODEL=mixedbread-ai/mxbai-embed-large-v1` é uma variável
de ambiente e corta o residente de 2,5 GiB para 0,64 GiB. Mais reindexar
os 40 vectores.

**Mas não é de graça:** a qualidade da pesquisa entre PT e EN cai de
0,917 para 0,549, medido. Numa plataforma que serve conteúdo nas duas
línguas, isso é uma regressão de produto que ninguém vai ver acontecer —
as respostas ficam piores sem nada falhar.

Só faz sentido como paragem de emergência, e com data para sair.

### Porque não nós maiores

`t3.large` → `t3.xlarge` duplica o custo do nó, todos os meses, para
alojar um processo que está em 195 MiB a maior parte do tempo. Paga-se
para sempre um pico que dura segundos e que não devia estar ali.

## 6. O que pode correr mal — e o que verificar

| risco | como se manifesta | verificação |
|---|---|---|
| reindexar metade | pesquisa degradada, **sem erro nenhum** | contar vectores antes/depois nas duas bases; devem bater |
| esquecer a base de um cliente | só esse cliente responde mal | correr o `/discover` por cliente, não só na plataforma |
| o Job de indexação herdar o mesmo limite | troca-se o sítio da morte | dar-lhe limite próprio e verificar que o pod de serviço fica em ~200 MiB |
| o mxbai como "temporário" que fica | qualidade pior para sempre | se se usar, abrir logo o trabalho de saída |
| o teste voltar a forçar indexação | volta tudo ao princípio | `test_smoke_nao_reindexa_sempre.py` já falha o PR |

**Como se sabe que resultou:** o `sky-ai` responde às 20 perguntas sem
reiniciar, e `kubectl top pod` mostra-o abaixo de 1 GiB durante a corrida.
Hoje sobe para lá dos 5 GiB e morre.

## 7. Correcção à recomendação, e a decisão

> «não sei que decisão tenho que tomar, mas é a mais segura e que não
>  aconteça mais» — Lucas, 08/10/2026

Com esse critério fui verificar a recomendação da §5 antes de a executar.
**Está errada.** Fica aqui o que a desmente, porque é mais útil do que
reescrevê-la.

### A §5 não teria evitado o que aconteceu

A §5 diz que o modelo «só é preciso quando se liga ou refresca uma
fonte». Não é verdade. O caminho das PERGUNTAS carrega-o, em três sítios
independentes de `api/routes/connection_query.py`:

| linha | o que faz | é dispensável? |
|---|---|---|
| 3446 | **cache semântico**: embute TODA a pergunta com ≥10 caracteres | sim, é uma optimização |
| 4482 | **RAG**: encontra as tabelas certas por semelhança | **não — é a função** |
| 5486 | idem, no outro ramo da mesma rota | **não** |

O 4482 e o 5486 são o que faz a IA saber a que tabelas se referem as
palavras da pessoa. Sem embeddings no caminho do pedido, não há produto.

E o 3446, que **é** dispensável, não se pode desligar: o `CLAUDE.md`
dizia que o cache semântico era controlado por `ENABLE_INFERENCE_CACHE`,
e **não é**. Essa definição guarda o LRU em processo do
`core/llm/cache.py`, que é outro cache. O semântico vive inline na rota e
corre sempre. (Corrigido no `CLAUDE.md` neste mesmo trabalho.)

Resistir à tentação de lhe pôr uma bandeira agora: com o 4482 e o 5486 a
carregar o mesmo modelo, desligar o 3446 não tira um único byte do pod —
só daria a ilusão de uma correcção.

Logo: tirar a indexação do pod **não** devolve o serviço aos 200 MiB, e
**não** teria impedido a morte durante o teste das 20 perguntas — que foi
exactamente o que aconteceu. Foram as perguntas que carregaram o modelo,
não a indexação.

### O mecanismo, que agora encaixa com todos os números

Faltava explicar porque é que 2,5 GiB residentes mataram um limite de
5 GiB. Encaixa assim:

```
resources:                      # values-sky-ai-prd-aws.yaml
  requests: { memory: 3Gi }     <-- a fatia GARANTIDA
  limits:   { memory: 5Gi }     <-- o tecto
```

`requests ≠ limits` dá ao pod a classe **Burstable**. Garantido tem
3 GiB; acima disso usa folga do nó, que **não é dele**. E o nó tem
5,2 GiB de 6,9 GiB já comprometidos.

Sob pressão de memória, o kubelet desaloja os **Burstable primeiro**. Ou
seja: provavelmente não bateu no tecto de 5 GiB — foi **desalojado pelo
nó** por estar a usar emprestado. É consistente com morrer a 2,5 GiB, o
que o tecto de 5 GiB nunca explicaria.

### E uma coisa que não tem desculpa

```python
# run_api.py — isto está em PRODUÇÃO
uvicorn.run("api.main:app", host="0.0.0.0", port=8001, reload=True)
```

`reload=True` é uma definição de desenvolvimento. Põe um vigilante de
ficheiros a observar o `/app` todo e um processo supervisor por cima, e
reinicia o worker a cada alteração que ele ache que viu. Num reinício,
dois workers podem coexistir por instantes — cada um com o seu modelo.

Não afirmo que foi isto que matou o pod. Afirmo que não devia estar
ligado, que custa uma linha, e que não tem nenhuma contrapartida.

### A decisão

**Três passos, por ordem de segurança e de custo.**

**1 — Hoje, e reversível (o travão).**
   `reload=True` fora, e o modelo a vir na imagem em vez de ser
   descarregado do `huggingface.co` a cada arranque. Zero custo, zero
   perda de qualidade, zero risco.
   ⚠️ **Nos recursos, não tocar** — ver a medição mais abaixo. A minha
   primeira versão deste passo propunha `requests` = `limits` e estava
   errada por três razões; foi revertida antes de sair.

**2 — A correcção de verdade: um serviço de embeddings.**
   Um pod pequeno, com o modelo bom (0,917) carregado uma vez, e todos os
   chamadores — perguntas, agentes, dashboards, indexação — a falar com
   ele por HTTP. Os 2,5 GiB passam a existir **num sítio só**, com
   limite próprio e numa máquina escolhida para isso. Os pods de serviço
   caem para ~300 MiB e voltam a poder escalar.
   É a única saída que mantém a qualidade, não tem custo recorrente além
   de um pod, e **acaba com a classe do problema** em vez de a mudar de
   sítio. Custa trabalho de engenharia.

**3 — O que fica mais barato depois, e não antes.**
   Com o modelo fora do caminho do pedido, o cache semântico (linha 3446)
   deixa de ser o que carrega 2,5 GiB para embutir uma pergunta, e passa
   a ser o que devia ser: uma chamada HTTP de milissegundos.

### O que foi rejeitado, e porquê

| caminho | porque não |
|---|---|
| modelo menor (`mxbai`) | 0,549 contra 0,917 na pesquisa PT↔EN. Vendemos a Espanha com equipa portuguesa: essa travessia **é** o produto. Uma regressão que ninguém vê acontecer é a pior de todas |
| nós maiores (`t3.xlarge`) | duplica a factura do nó todos os meses e **não corrige a causa** — só compra silêncio até à próxima réplica |
| «subir o limite para 6 GiB» | o nó tem 6,9 GiB e já tem 5,2 comprometidos. Só muda quem morre |

### Medido em produção depois de escrever o acima — e muda a conclusão

Fui medir no pod em vez de confiar na inferência. Três números que
desmontam parte do que está escrito nesta secção:

```
memória AGORA, com o modelo JÁ carregado         1566 Mi
perguntas servidas por este pod                     4
reinícios / último estado                       0 / vazio
classe de QoS                                   Burstable
```

O modelo está carregado — o `TextEmbedding` aparece nos registos — e o
pod está a **1,5 GiB**, não a 2,5 nem perto dos 5. Os 2,7 GiB do
documento são o pico **da indexação**, não do serviço.

**Isto derruba a minha própria proposta de `requests` = `limits`,** por
três razões independentes:

1. **Não daria Guaranteed.** Essa classe exige requests = limits também
   no **CPU**, e aqui é 500m contra 4000m. Igualar o CPU significaria
   reservar 4 vCPU num `t3.large` que tem 2 — o pod nunca agendava.
2. **Baixar o tecto introduzia um risco novo.** De 5Gi para 4Gi é MENOS
   folga para o pico da indexação (2,7 GiB mais o resto). Trocava uma
   morte por outra.
3. **E era desnecessário.** O `request` de 3 GiB **já é o dobro** do uso
   em repouso. Um pod Burstable que consome MENOS do que o seu request é
   o último a ser desalojado — a mesma posição de um Guaranteed. A minha
   hipótese do desalojamento não se aplica ao estado estável.

A alteração foi revertida antes de sair. Fica aqui porque o erro é
instrutivo: inferi uma classe de QoS a partir de dois números no YAML e
não fui ver o terceiro, que era o uso real.

### Então o que resta, e onde as duas versões concordam

O pico não é das perguntas em repouso: é da **indexação** (2,7 GiB), que
empurra o pod acima do seu request e para território emprestado —
exactamente onde o nó, com 73% da memória e 90% do CPU já pedidos, o
desaloja.

O que significa que a §5 e esta correcção apontam para **o mesmo sítio**,
por razões diferentes:

| | o que dizia | estava |
|---|---|---|
| §5 | tirar a indexação do pod devolve-o a 200 MiB | **errado no motivo** — as perguntas carregam o modelo em 3 sítios |
| §5 | o modelo não deve viver no pod que serve | **certo** |
| eu, acima | é um problema de classe de QoS | **errado** — o request já cobre o uso |

**A decisão não muda: o modelo tem de sair do caminho do pedido.** Um
serviço de embeddings resolve as duas coisas de uma vez — tira o pico da
indexação e tira o residente das perguntas.

### E uma coisa que apareceu nos registos, que ninguém tinha visto

```
HTTP Request: GET https://huggingface.co/api/models/Qdrant/multilingual-e5-large-onnx ...
```

**O modelo é descarregado da internet a cada arranque do pod.** Em
produção. Se o `huggingface.co` estiver em baixo, ou mudar o caminho do
repositório, ou nos limitar o débito, o serviço de IA não arranca — e a
causa não vai parecer nossa.

Independentemente do serviço de embeddings: o modelo tem de vir **na
imagem** ou de um volume. É mais barato de fazer do que de explicar.

### O que fica por saber, e já não é possível saber

O pod foi recriado depois das mortes (`restarts: 0`, último estado
vazio), e os eventos do namespace já expiraram. **Não há como distinguir
`OOMKilled` de `Evicted` naquelas duas mortes.** Na próxima — se houver —
a primeira coisa a fazer é `kubectl describe pod` antes de qualquer
reinício.
