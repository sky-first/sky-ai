# run_api.py
#
# O arranque do serviço de IA, em produção e em desenvolvimento.
#
# ── Porque é que o `reload` não está aqui ligado por omissão ────────
#
# Estava, e a correr em produção: `uvicorn.run(..., reload=True)`.
#
# O `reload` do uvicorn não é um comodismo — é outra arquitectura. Põe um
# processo supervisor por cima, um vigilante a observar a árvore do
# `/app` toda, e reinicia o worker a cada alteração que ache que viu. Num
# reinício, dois workers podem coexistir por instantes — e cada worker
# deste serviço tem um modelo de embeddings de ~2,5 GiB residentes.
#
# O pod morreu por falta de memória duas vezes em duas horas, com uma só
# réplica — cada morte é a aplicação em baixo para todos. Não está
# provado que tenha sido isto; está provado que isto não devia estar
# ligado, que custa uma linha e que não tem contrapartida nenhuma.
#
# Ver `docs/plano-memoria-da-indexacao.md`.
from dotenv import load_dotenv

load_dotenv()

import os

import uvicorn

#: Recarregamento automático ao editar ficheiros. **Só em
#: desenvolvimento**, e só quando se pede de propósito — nunca por
#: omissão, para não voltar a produção por distracção.
RECARREGAR = os.getenv("API_RELOAD", "").strip().lower() in {"1", "true", "yes"}

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8001,
        reload=RECARREGAR,
    )
