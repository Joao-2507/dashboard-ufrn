# 🎓 Dashboard de Dados Abertos da UFRN

Dashboard interativo desenvolvido em **Python e Streamlit** para exploração, visualização e análise dos dados abertos de ensino da Universidade Federal do Rio Grande do Norte (UFRN).

O projeto utiliza um banco de dados **SQLite** construído a partir de conjuntos de dados disponibilizados pelo Portal de Dados Abertos da UFRN.

## 1. Objetivo do projeto

O objetivo é facilitar a exploração e interpretação de informações acadêmicas por meio de uma interface visual e interativa.

O dashboard permite consultar informações institucionais, acompanhar distribuições e tendências, explorar tabelas e visualizar indicadores relacionados ao ensino superior.

## 2. Tecnologias utilizadas

| Tecnologia | Finalidade |
|---|---|
| Python | Linguagem principal do projeto |
| Streamlit | Desenvolvimento da interface web |
| Pandas | Manipulação e análise de dados |
| Plotly | Construção de gráficos interativos |
| SQLite | Armazenamento e consulta dos dados |
| SQL | Consultas e agregações |
| Git e GitHub | Versionamento e armazenamento do código |

## 3. Funcionalidades do dashboard

O dashboard está organizado nas seguintes seções:

### Visão geral
- Panorama dos dados disponíveis.
- Indicadores quantitativos.
- Exploração das principais tabelas do banco.

### Discentes
- Análise de registros acadêmicos.
- Distribuição de informações relacionadas aos discentes.
- Evolução temporal, quando disponível.

### Matrículas
- Análise dos registros de matrículas.
- Distribuição por categorias acadêmicas.
- Visualização de tendências.

### Cursos
- Exploração de informações dos cursos.
- Distribuição dos registros por categorias.
- Indicadores relacionados à oferta acadêmica.

### Docentes e turmas
- Análise de informações sobre docentes e turmas.
- Exploração das distribuições disponíveis.
- Visualização de indicadores e gráficos.

### Biblioteca
- Exploração dos registros relacionados às bibliotecas.
- Análise de distribuições e evolução temporal, conforme a disponibilidade dos dados.

### Explorador SQL
- Visualização das tabelas do banco SQLite.
- Consulta aos campos disponíveis.
- Exploração dos registros armazenados.

**Observação:** as visualizações dependem das tabelas e colunas efetivamente disponíveis no banco. Nem todos os conjuntos de dados possuem a mesma cobertura temporal.

## 4. Estrutura do projeto

```text
dashboard-ufrn/
│
├── README.md
├── .gitignore
│
├── dados_abertos_ufrn_ensino-main/
│   ├── baixar.py
│   ├── construir_banco.py
│   ├── parser_tolerante.py
│   ├── requirements.txt
│   ├── README.md
│   └── .gitignore
│
└── dashboard_ufrn_streamlit/
    ├── app.py
    ├── requirements.txt
    └── COMO_EXECUTAR.md
```

O banco `ufrn_ensino.db`, os arquivos brutos e os ambientes virtuais não são incluídos no repositório. Eles são gerados ou configurados localmente.

---

# 5. Como executar o projeto

As instruções a seguir foram preparadas para **Windows, utilizando PowerShell no Visual Studio Code**.

## Etapa 1 — Pré-requisitos

Antes de iniciar, é necessário ter instalado:

- Python 3.10 ou superior.
- Visual Studio Code ou outro editor de código.
- Git, caso queira clonar o repositório pelo terminal.
- Conexão com a internet para baixar os dados.

Recomenda-se reservar aproximadamente **8 GB de espaço livre** durante a construção do banco de dados.

## Etapa 2 — Baixar o repositório

Acesse:

https://github.com/Joao-2507/dashboard-ufrn

Clique em:

**Code → Download ZIP**

Extraia o arquivo ZIP em uma pasta de sua preferência.

Alternativamente, utilize o Git:

```powershell
git clone https://github.com/Joao-2507/dashboard-ufrn.git
```

## Etapa 3 — Abrir o projeto no VS Code

Abra o Visual Studio Code.

Selecione:

**File → Open Folder**

Escolha a pasta `dashboard-ufrn`.

Em seguida, abra um terminal:

**Terminal → New Terminal**

## Etapa 4 — Preparar o ambiente para obtenção dos dados

No terminal, entre na pasta dos scripts:

```powershell
cd dados_abertos_ufrn_ensino-main
```

Crie um ambiente virtual:

```powershell
python -m venv .venv
```

Ative o ambiente:

```powershell
.\.venv\Scripts\Activate.ps1
```

Caso a ativação seja bloqueada pelo PowerShell, execute:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Depois, tente ativar o ambiente novamente.

Instale as dependências:

```powershell
python -m pip install -r requirements.txt
```

## Etapa 5 — Baixar os dados da UFRN

Execute:

```powershell
python baixar.py
```

O script consulta o Portal de Dados Abertos da UFRN e realiza o download dos conjuntos de dados configurados no projeto.

Durante o processo, são gerados:

- `arquivos/`: diretório contendo os dados e dicionários baixados.
- `manifesto.json`: metadados dos recursos obtidos.

O tempo necessário depende da conexão com a internet e do volume de arquivos.

**Nota de segurança:** o script original utiliza requisições HTTPS com a verificação de certificados desabilitada para contornar problemas na cadeia de certificados do portal. Essa configuração reduz a segurança da conexão e deve ser revisada antes de sua utilização.

## Etapa 6 — Construir o banco SQLite

Após concluir os downloads, execute:

```powershell
python construir_banco.py
```

Esse script processa os dados e constrói o banco SQLite consolidado.

Ao final, será criado o arquivo:

```text
dados_abertos_ufrn_ensino-main/
└── ufrn_ensino.db
```

O banco poderá ocupar vários gigabytes de armazenamento.

**Importante:** executar novamente `construir_banco.py` recria o banco de dados. Portanto, mantenha uma cópia caso queira preservar uma versão anterior.

## Etapa 7 — Disponibilizar o banco para o dashboard

O dashboard precisa acessar o banco SQLite.

Copie o arquivo:

```text
dados_abertos_ufrn_ensino-main/ufrn_ensino.db
```

Para:

```text
dashboard_ufrn_streamlit/ufrn_ensino.db
```

Após a cópia, a estrutura deverá ficar assim:

```text
dashboard-ufrn/
│
├── dados_abertos_ufrn_ensino-main/
│   └── ufrn_ensino.db
│
└── dashboard_ufrn_streamlit/
    ├── app.py
    ├── requirements.txt
    ├── COMO_EXECUTAR.md
    └── ufrn_ensino.db
```

A cópia do banco é necessária porque o arquivo `app.py` procura `ufrn_ensino.db` no mesmo diretório em que está localizado.

## Etapa 8 — Preparar o ambiente do dashboard

No terminal do VS Code, estando dentro da pasta `dados_abertos_ufrn_ensino-main`, execute:

```powershell
cd ..\dashboard_ufrn_streamlit
```

Crie o ambiente virtual:

```powershell
python -m venv .venv
```

Ative-o:

```powershell
.\.venv\Scripts\Activate.ps1
```

Instale as bibliotecas:

```powershell
python -m pip install -r requirements.txt
```

## Etapa 9 — Executar o dashboard

Com o banco SQLite na pasta correta e as dependências instaladas, execute:

```powershell
python -m streamlit run app.py
```

O Streamlit iniciará um servidor local.

Abra o endereço:

**http://localhost:8501**

O dashboard deverá ser exibido no navegador.

## Etapa 10 — Como acessar novamente

Depois da configuração inicial, não é necessário baixar os dados ou reconstruir o banco a cada utilização.

Abra o projeto no VS Code e, no terminal localizado na pasta principal, execute:

```powershell
cd dashboard_ufrn_streamlit
```

Ative o ambiente virtual:

```powershell
.\.venv\Scripts\Activate.ps1
```

Inicie a aplicação:

```powershell
python -m streamlit run app.py
```

Acesse novamente:

http://localhost:8501

Para encerrar o servidor, pressione `Ctrl + C` no terminal.

---

## 6. Organização e processamento dos dados

O processamento dos dados segue três etapas principais:

**1. Coleta:** o script `baixar.py` obtém os recursos do Portal de Dados Abertos da UFRN.

**2. Tratamento e integração:** o script `construir_banco.py`, com apoio de `parser_tolerante.py`, realiza o processamento e a consolidação das informações.

**3. Visualização:** o aplicativo `app.py` realiza consultas ao banco SQLite e apresenta indicadores, gráficos e tabelas por meio do Streamlit.

O dashboard utiliza consultas SQL agregadas para reduzir a necessidade de carregar tabelas inteiras na memória.

## 7. Fonte dos dados

Os dados são provenientes do Portal de Dados Abertos da Universidade Federal do Rio Grande do Norte.

**Portal:** https://dados.ufrn.br/

**Grupo de dados de ensino:** https://dados.ufrn.br/dataset?groups=ensino

Os conjuntos de dados podem apresentar diferentes períodos de cobertura, estruturas e níveis de atualização.

O projeto utiliza os scripts de coleta e consolidação presentes na pasta `dados_abertos_ufrn_ensino-main`. Consulte o README original dessa pasta para informações adicionais sobre o processamento.

## 8. Limitações e observações

- O banco SQLite completo não está disponível neste repositório.
- A execução inicial exige o download e processamento dos dados.
- O volume do banco pode exigir espaço de armazenamento e tempo de processamento consideráveis.
- Algumas visualizações dependem da existência de colunas específicas.
- As contagens de registros não representam necessariamente quantidades de pessoas únicas.
- O dashboard foi preparado para execução local e não possui sistema de autenticação.

## 9. Possíveis melhorias futuras

- Implementação de filtros acadêmicos adicionais.
- Criação de novos indicadores de desempenho.
- Comparações entre cursos e períodos.
- Aprimoramento da interface visual.
- Otimização de consultas SQL.
- Publicação do dashboard em ambiente web.
- Automatização da atualização dos dados.

GitHub: https://github.com/Joao-2507

---

**Projeto desenvolvido para fins de estudo, exploração de dados e desenvolvimento de habilidades em análise de dados, bancos de dados e visualização interativa.**
