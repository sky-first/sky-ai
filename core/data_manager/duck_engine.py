
import duckdb
import pandas as pd
from typing import List, Dict, Any, Optional

class DuckEngine:
    """
    Motor de processamento de dados local usando DuckDB.
    Permite carregar dados em memória e executar SQL analítico.
    """
    def __init__(self):
        # Conexão em memória volátil
        self.conn = duckdb.connect(database=':memory:')
        
    def register_data(self, table_name: str, data: List[Dict[str, Any]]) -> None:
        """
        Registra uma lista de dicionários como uma tabela SQL.
        
        Args:
            table_name: Nome da tabela (alias)
            data: Lista de registros (ex: [{'id': 1}, {'id': 2}])
        """
        if not data:
            print(f"Warning: Empty data for {table_name}")
            # Cria tabela vazia se necessário ou ignora warning
            return

        # Converte para DataFrame (DuckDB ingere Pandas eficientemente)
        df = pd.DataFrame(data)
        
        # Registra no DuckDB
        # overwrite=True implícito ao registrar novamente com mesmo nome na sessão
        self.conn.register(table_name, df)
        
    def execute(self, sql: str) -> List[Dict[str, Any]]:
        """
        Executa SQL e retorna resultado como lista de dicts.
        Garante que tipos (Date, Decimal) sejam serializáveis.
        """
        try:
            # Execute e fetch como Arrow -> Pandas para controle de tipos
            # Ou fetchdf() direto
            result_df = self.conn.execute(sql).fetchdf()
            
            # Converter NaN/Inf para None (JSON null) e 0, respectivamente
            # replace({np.nan: None}) não funciona bem em todas versões pandas com tipos nativos
            # Melhor abordagem: converter para object onde tem nulls ou usar where
            
            # 1. Tratar Infinitos
            result_df = result_df.replace([float("inf"), float("-inf")], 0)
            
            # 2. Tratar NaNs de forma segura (sem forçar string "")
            # Converter para dict e depois limpar NaNs é mais seguro que fillna("") em colunas numéricas
            records = result_df.to_dict(orient="records")
            
            # Limpeza manual de NaN pré-serialização (para garantir JSON valid)
            clean_records = []
            for row in records:
                clean_row = {}
                for k, v in row.items():
                    # Check for actual NaN (float('nan'))
                    if isinstance(v, float) and v != v:
                        clean_row[k] = None
                    # Check for Pandas <NA>
                    elif pd.isna(v): 
                        clean_row[k] = None
                    else:
                        clean_row[k] = v
                clean_records.append(clean_row)

            return clean_records
            
        except Exception as e:
            # Relançar ou tratar erro SQL
            raise RuntimeError(f"DuckDB Execution Error: {str(e)}")

    def close(self):
        """Fecha conexão (libera memória)."""
        self.conn.close()
