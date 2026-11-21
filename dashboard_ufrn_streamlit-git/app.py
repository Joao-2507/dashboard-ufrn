import sqlite3
from pathlib import Path
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title='UFRN | Observatório do Ensino', page_icon='🎓', layout='wide')
st.title('🎓 Observatório do Ensino — UFRN')
st.caption('Dashboard exploratório baseado no banco SQLite de Dados Abertos de Ensino da UFRN')

DB = Path(__file__).resolve().parent / 'ufrn_ensino.db'
if not DB.exists():
    st.error('Banco não encontrado. Execute baixar.py e construir_banco.py e coloque ufrn_ensino.db na pasta deste app.')
    st.stop()

@st.cache_data(show_spinner=False, ttl=3600)
def schema():
    with sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True) as con:
        tables = pd.read_sql_query("SELECT name,type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name", con)
        columns = {}
        for name in tables['name']:
            safe = name.replace('"','""')
            columns[name] = [r[1] for r in con.execute(f'PRAGMA table_info("{safe}")')]
    return tables, columns

@st.cache_data(show_spinner='Consultando banco…', ttl=3600)
def query(sql, params=()):
    with sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True, timeout=30) as con:
        return pd.read_sql_query(sql, con, params=params)

def ident(name):
    return '"' + name.replace('"','""') + '"'

def choose(cols, candidates):
    lookup = {x.lower():x for x in cols}
    for c in candidates:
        if c.lower() in lookup:
            return lookup[c.lower()]
    return None

def chart(df, x, y, title, kind='line'):
    if df.empty:
        st.info('Não há registros para o recorte selecionado.')
        return
    fig = (px.line(df, x=x, y=y, markers=True, title=title) if kind == 'line'
           else px.bar(df, x=x, y=y, title=title))
    fig.update_layout(margin=dict(l=10,r=10,t=55,b=10), height=380)
    st.plotly_chart(fig, use_container_width=True)

def download(df, name):
    st.download_button('⬇️ Exportar dados do gráfico (CSV)', df.to_csv(index=False).encode('utf-8-sig'), name, 'text/csv')

def yearly(table, cols, title):
    year = choose(cols, ['ano', 'ano_referencia', 'ano_ingresso', 'ano_entrada', 'ano_letivo', 'ano_conclusao', 'ano_saida'])
    if not year:
        st.info(f'{table}: não foi encontrada uma coluna de ano reconhecida. Confira o Explorador SQL.')
        return
    q = f'SELECT CAST({ident(year)} AS INTEGER) AS ano, COUNT(*) AS registros FROM {ident(table)} WHERE {ident(year)} IS NOT NULL AND CAST({ident(year)} AS INTEGER) BETWEEN 1990 AND 2035 GROUP BY 1 ORDER BY 1'
    df = query(q)
    if df.empty:
        st.warning('Sem dados anuais disponíveis.')
        return
    years = st.slider('Período', int(df.ano.min()), int(df.ano.max()), (int(df.ano.min()), int(df.ano.max())), key='years_'+table)
    df = df[df.ano.between(*years)]
    st.metric('Registros no período', f'{df.registros.sum():,}'.replace(',','.'))
    chart(df,'ano','registros',title)
    download(df, f'{table}_por_ano.csv')
    st.caption('Contagem de registros da tabela por ano; não representa necessariamente pessoas únicas.')

def top(table, cols, candidates, title):
    field = choose(cols,candidates)
    if not field:
        st.info(f'Não há coluna compatível para {title.lower()} em {table}.')
        return
    df = query(f'SELECT CAST({ident(field)} AS TEXT) AS categoria, COUNT(*) AS registros FROM {ident(table)} WHERE {ident(field)} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 20')
    chart(df,'categoria','registros',title,'bar')
    download(df, f'{table}_categorias.csv')

try:
    tables, columns = schema()
except Exception as e:
    st.error(f'Erro ao abrir o banco: {e}')
    st.stop()

names = set(tables.name)
page = st.sidebar.radio('Navegação', ['Visão geral','Discentes','Matrículas','Cursos','Docentes e turmas','Biblioteca','Explorador SQL'])
st.sidebar.caption('Consultas agregadas executadas diretamente no SQLite. O banco é aberto somente para leitura.')

if page == 'Visão geral':
    st.subheader('Panorama dos dados disponíveis')
    base = [t for t in ['discentes','egressos','cursos','docentes','turmas','matriculas_componentes','emprestimos'] if t in names]
    for start in range(0,len(base),4):
        cols = st.columns(4)
        for c,t in zip(cols,base[start:start+4]):
            # COUNT(*) pode ser custoso em tabelas muito grandes; é executado sob demanda e cacheado.
            n = int(query(f'SELECT COUNT(*) AS n FROM {ident(t)}').iloc[0].n)
            c.metric(t.replace('_',' ').title(), f'{n:,}'.replace(',','.'))
    st.info('As métricas acima contam linhas das tabelas. Turmas pode ter mais de uma linha por turma (turma × docente).')
    st.dataframe(tables, use_container_width=True, hide_index=True)

elif page == 'Discentes':
    st.subheader('Análise de discentes')
    if 'discentes' in names:
        yearly('discentes',columns['discentes'],'Ingressantes / registros de discentes por ano')
        top('discentes',columns['discentes'],['nivel_ensino','nivel','modalidade','status'],'Distribuição dos discentes')
    if 'egressos' in names:
        st.divider(); st.subheader('Egressos')
        yearly('egressos',columns['egressos'],'Registros de egressos por ano')

elif page == 'Matrículas':
    st.subheader('Matrículas em componentes curriculares')
    if 'matriculas_componentes' in names:
        t='matriculas_componentes'
        yearly(t,columns[t],'Evolução de registros de matrículas em componentes')
        top(t,columns[t],['descricao','situacao','status','descricao_situacao'],'Situação das matrículas')
    st.warning('Matrículas em componentes não são equivalentes a alunos únicos. Não faça JOIN direto com turmas sem agregação.')

elif page == 'Cursos':
    st.subheader('Cursos')
    if 'cursos' in names:
        t='cursos'
        st.metric('Registros de cursos (cadastro atual)',f"{int(query('SELECT COUNT(*) AS n FROM cursos').iloc[0].n):,}".replace(',','.'))
        top(t,columns[t],['nivel_ensino','nivel','modalidade','municipio','campus','tipo'],'Cursos por classificação')
    for t in ['cursos_graduacao','cursos_pos_graduacao','cursos_tecnicos']:
        if t in names:
            st.metric(t.replace('_',' ').title(), f"{int(query('SELECT COUNT(*) AS n FROM '+ident(t)).iloc[0].n):,}".replace(',','.'))
    st.caption('O cadastro de cursos representa o estado atual e pode não incluir cursos históricos descontinuados.')

elif page == 'Docentes e turmas':
    st.subheader('Docência e oferta de turmas')
    if 'turmas' in names:
        t='turmas'; cols=columns[t]
        year=choose(cols,['ano','ano_referencia'])
        idturma=choose(cols,['id_turma'])
        if year and idturma:
            df=query(f'SELECT CAST({ident(year)} AS INTEGER) AS ano, COUNT(DISTINCT {ident(idturma)}) AS turmas FROM turmas WHERE CAST({ident(year)} AS INTEGER) BETWEEN 1990 AND 2035 GROUP BY 1 ORDER BY 1')
            chart(df,'ano','turmas','Turmas distintas ofertadas por ano')
            download(df,'turmas_por_ano.csv')
        else:
            yearly(t,cols,'Registros de turmas por ano')
    if 'docentes' in names:
        st.metric('Docentes no cadastro atual',f"{int(query('SELECT COUNT(*) AS n FROM docentes').iloc[0].n):,}".replace(',','.'))
    st.caption('A tabela turmas contém uma linha por turma × docente. O gráfico utiliza COUNT(DISTINCT id_turma).')

elif page == 'Biblioteca':
    st.subheader('Empréstimos e acervo')
    if 'emprestimos' in names:
        t='emprestimos'; cols=columns[t]
        yearly(t,cols,'Evolução anual de empréstimos')
        top(t,cols,['tipo_emprestimo','tipo_usuario','biblioteca','status'],'Empréstimos por categoria')
    for t in ['acervo_titulos','acervo_exemplares']:
        if t in names:
            st.metric(t.replace('_',' ').title(),f"{int(query('SELECT COUNT(*) AS n FROM '+ident(t)).iloc[0].n):,}".replace(',','.'))
    st.caption('O cadastro de exemplares é atual; empréstimos antigos podem referenciar exemplares não cadastrados hoje.')

else:
    st.subheader('Explorador de tabelas e colunas')
    t=st.selectbox('Tabela ou view',list(tables.name))
    st.write('Colunas:',', '.join(columns[t]))
    n=st.slider('Quantidade de linhas de amostra',5,100,20)
    st.dataframe(query(f'SELECT * FROM {ident(t)} LIMIT ?', (n,)),use_container_width=True)
    st.caption('Este explorador permite conferir os nomes reais das colunas e adaptar análises específicas.')
