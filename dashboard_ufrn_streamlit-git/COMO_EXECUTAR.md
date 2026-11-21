# Dashboard de Dados Abertos de Ensino da UFRN

## 1. Gerar o banco (projeto original)

Extraia `dados_abertos_ufrn_ensino-main.zip` e, na pasta extraída, abra um terminal:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python baixar.py
python construir_banco.py
```

**Atenção:** o ZIP original contém os scripts, não o banco. O README estima aproximadamente 8 GB de espaço livre durante o pipeline e acesso à internet. O código de download original desativa a verificação de certificados HTTPS (`verify=False`); avalie o risco de segurança antes de executá-lo.

## 2. Rodar o dashboard

Copie `ufrn_ensino.db` gerado para a mesma pasta que `app.py` deste dashboard. No terminal dessa pasta:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Abra o endereço local exibido (geralmente http://localhost:8501).

## Observações

- As análises são calculadas do banco real; não foram inseridos valores simulados.
- O app usa consultas SQL agregadas para evitar carregar tabelas inteiras na memória.
- O reconhecimento automático de colunas de ano e categoria é conservador: se a tabela usar outro nome, consulte o Explorador SQL e ajuste as listas de candidatos em `app.py`.
- Os dados históricos têm coberturas diferentes; nem toda série é comparável.
- A consulta inicial `COUNT(*)` pode levar tempo em tabelas muito grandes.
- Não há autenticação no app: use localmente ou implemente controle de acesso antes de publicar.
