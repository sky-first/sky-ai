"""Perguntas que nenhuma base de dados de empresa pode responder.

O Lucas pediu isto por palavras dele:

    «Ele pode falar tipo *bom dia, como vai por aí?* ou, *quantos graus
    fazem hoje em Lisboa*, ou coisas simples que poderíamos sim responder
    sem ir aos dados.»

A primeira parte ficou feita — os cumprimentos. A segunda não, e vi-o em
produção depois de publicar:

    «Quantos graus fazem hoje em Lisboa?»  →  data

Ia ao motor de SQL, que não tem tabela de meteorologia nenhuma, e a
pessoa recebia a fórmula de erro.

── Porque é que o detector de conversa não a apanhava ───────────────

Ele exige três coisas: um padrão de cumprimento, poucas palavras, e
**zero** sinais de negócio. Esta frase falha logo na primeira (não é um
cumprimento) e falharia na terceira de qualquer maneira: «quantos» e
«hoje» são sinais de dados — que eu próprio lá pus, para o português
deixar de ser invisível.

E é uma tensão real, não um descuido: «quantos» e «hoje» **são** palavras
de negócio. «Quantos clientes fecharam hoje?» é uma pergunta a sério.

── A regra ─────────────────────────────────────────────────────────

O que distingue as duas não é a forma da pergunta, é o **assunto**. O
tempo em Lisboa, as horas, quem ganhou o jogo — são coisas do mundo, e
nenhum cliente tem isso na sua base de dados.

Por isso estes padrões ganham ao sinal de negócio. São a única coisa
nesta pasta que o faz, e é por isso que são escritos com tanto medo.

── O medo, e o que se faz com ele ──────────────────────────────────

Roubar uma pergunta de negócio é muito pior do que deixar passar uma
pergunta sobre o tempo: a primeira perde trabalho, a segunda é só
estranha. Por isso:

* nenhum padrão é uma palavra sozinha. «temperatura» sozinha apanhava
  *«temperatura média dos sensores»*, que é uma pergunta a sério para
  quem tem fábricas. «horas» sozinha apanhava *«quantas horas trabalhou
  a equipa?»*. «tempo» sozinha apanhava *«tempo médio de entrega»* — a
  pior de todas, porque é uma métrica comuníssima;
* cada padrão exige a forma inteira («que horas são», «quantos graus»),
  e não o substantivo;
* o ficheiro de testes tem uma lista de quase-erros — perguntas de
  negócio que se parecem com estas — e cada padrão novo tem de passar
  por lá antes de entrar.
"""

from __future__ import annotations

import re

#: Assuntos do mundo, não da empresa.
#:
#: Cada entrada esta escrita para nao poder ser confundida com uma
#: metrica. Ver o modulo inteiro para o porque.
_MUNDO = re.compile(
    r"("
    # ── o tempo que faz ──────────────────────────────────────────
    # «temperatura» e «tempo» sozinhas sao metricas legitimas; so
    # contam com a forma toda.
    # «graus de …» fica de fora: «quantos graus de satisfacao temos?» e
    # uma metrica, e a lista de quase-erros apanhou-a.
    r"quantos?\s+graus(?!\s+de\b)|"
    r"graus\s+(faz|fazem|est[aá])|"
    r"que\s+tempo\s+(faz|est[aá])|"
    r"como\s+est[aá]\s+o\s+tempo|"
    r"vai\s+chover|est[aá]\s+a\s+chover|"
    r"previs[aã]o\s+do\s+tempo|"
    # «what's» nao chegava: «What IS the weather like today?» falhava.
    # «weather» nao e nome de nenhuma metrica, por isso aqui basta.
    r"\bweather\b|"
    r"is\s+it\s+going\s+to\s+rain|"
    r"qu[eé]\s+tiempo\s+hace|cu[aá]ntos\s+grados|"
    # ── as horas e o dia ─────────────────────────────────────────
    # «quantas horas» fica de fora de proposito: e uma metrica.
    r"que\s+horas\s+s[aã]o|"
    r"que\s+dia\s+[eé]\s+hoje|"
    r"what\s+time\s+is\s+it|what\s+day\s+is\s+(it|today)|"
    r"qu[eé]\s+hora\s+es|qu[eé]\s+d[ií]a\s+es\s+hoy|"
    # ── desporto e noticias ──────────────────────────────────────
    # «quem ganhou» sozinho e de negocio («quem ganhou mais este
    # mes»); exige-se o jogo.
    # «campeonato» e «liga» sairam: «quem ganhou o campeonato interno de
    # vendas?» e uma pergunta de negocio, e o padrao roubava-a. O
    # desporto e o assunto menos importante desta lista e nao vale o
    # risco — falhar um resultado de futebol custa muito menos do que
    # responder «nao sei» a um concurso de vendas.
    r"quem\s+ganhou\s+(o\s+)?(jogo|a\s+partida)|"
    r"who\s+won\s+the\s+(game|match)|"
    # ⚠️ Sem `|` a seguir a esta linha. Tinha um, e um `|` antes do
    # parentese deixa uma alternativa VAZIA no grupo — que casa com
    # qualquer frase. Toda e qualquer pergunta passava a ser «do mundo»,
    # incluindo «qual e a receita do trimestre».
    #
    # Nao chegou a sair daqui: a lista de quase-erros apanhou-o antes de
    # isto estar sequer ligado ao classificador. E ler o padrao nao o
    # mostrava — foram os quinze «ROUBADA» seguidos.
    r"not[ií]cias\s+de\s+hoje"
    r")",
    re.IGNORECASE,
)


def parece_do_mundo(pergunta: str) -> bool:
    """A pergunta e sobre o mundo, e nao sobre os dados de quem pergunta.

    Quando e, ganha ao sinal de negocio — porque nenhuma base de dados de
    cliente tem meteorologia, relogio ou resultados desportivos.
    """
    return bool(pergunta and _MUNDO.search(pergunta))
