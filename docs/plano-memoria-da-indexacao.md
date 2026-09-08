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

## 7. Decisão pendente

Está por decidir qual dos caminhos seguir. Este documento existe para
essa decisão ser tomada com os números à frente, e não com o palpite de
que «é preciso mais memória» — que foi a primeira reacção, e estava
errada por duas razões independentes: não cabia nos nós, e não era ali
que estava o problema.
