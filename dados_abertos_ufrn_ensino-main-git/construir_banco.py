"""
Constroi o banco SQLite 'ufrn_ensino.db' a partir dos arquivos baixados.

Decisoes de modelagem:
  - Arquivos de semestres diferentes do mesmo dataset vao para UMA tabela, com
    colunas 'ano_referencia'/'periodo_referencia' derivadas do nome do recurso
    (matriculas e emprestimos nao traziam essas colunas no CSV).
  - Os 3 CSVs de componentes curriculares (presencial/semi/EAD) viram uma tabela
    unica com a coluna 'origem_modalidade'.
  - O JSON dos PIDs e normalizado em 'pids' + 'pid_turmas' (1:N).
  - Os tipos sao declarados no CREATE TABLE. O SQLite aplica type affinity, logo
    inserir a string '123' numa coluna INTEGER grava o inteiro 123 -- e isso que
    faz os joins por id casarem entre tabelas.
"""
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

import parser_tolerante

csv.field_size_limit(10 ** 9)  # ementas e bibliografias sao campos enormes

RAIZ = Path(__file__).parent
BANCO = RAIZ / "ufrn_ensino.db"

# ---------------------------------------------------------------- mapeamentos

# Datasets em que TODO arquivo (qualquer ano/semestre) vai pra mesma tabela.
# Mapeado pelo nome do dataset (campo "dataset" do manifesto, = nome do
# pacote CKAN) em vez do nome exato do arquivo -- assim escala para qualquer
# profundidade historica (baixar.py/RECORTE) sem precisar listar cada ano.
DESTINO_POR_DATASET = {
    "matriculas-componentes": ("matriculas_componentes", "periodo_arquivo"),
    "turmas": ("turmas", None),
    "emprestimos-acervos-das-bibliotecas": ("emprestimos", "periodo_arquivo"),
    "discentes": ("discentes", None),
    "egressos": ("egressos", None),
    "situacoes-de-discentes": ("situacoes_discentes", "periodo_arquivo"),
    "orientacoes-docentes": ("orientacoes_docentes", "periodo_arquivo"),
    "cursos-ufrn": ("cursos", None),
    "cursos-de-graduacao": ("cursos_graduacao", None),
    "cursos-de-pos-graduacao": ("cursos_pos_graduacao", None),
    "cursos-tecnicos": ("cursos_tecnicos", None),
    "docentes": ("docentes", None),
    "docentes-externos": ("docentes_externos", None),
    "estruturas-curriculares": ("estruturas_curriculares", None),
    "curriculo-componente": ("curriculo_componente", None),
    "programas-de-pos-graduacao": ("programas_pos_graduacao", None),
    "avaliacoes-de-docencia": ("avaliacoes_docencia", None),
    "diplomas": ("diplomas", None),
    "trabalhos-de-conclusao-de-curso": ("tccs", None),
    "projetos-de-ensino": ("projetos_ensino", None),
}

# Excecoes por ARQUIVO: datasets cadastrais (poucos arquivos, nao afetados
# pela profundidade historica) em que o mesmo dataset carrega arquivos
# destinados a tabelas diferentes, ou que precisam de uma tag por arquivo.
DESTINO_POR_ARQUIVO = {
    "componentes-curriculares-presenciais.csv": ("componentes_curriculares", "origem_modalidade"),
    "componentes-curriculares-semi-presenciais.csv": ("componentes_curriculares", "origem_modalidade"),
    "componentes-curriculares-ead.csv": ("componentes_curriculares", "origem_modalidade"),
    "processos-seletivos-cursos-de-graduacao.csv": ("processos_seletivos_graduacao", None),
    # processos-seletivos-outros.csv tem rota propria (carregar_ps_outros)
    "exemplares.csv": ("acervo_exemplares", None),          # "Versao 2", mais recente
    "acervo.csv": ("acervo_exemplares_v1", None),           # versao anterior, mantida
    "exemplares-acervo.csv": ("acervo_titulos", None),      # catalogo bibliografico
}


def resolver_destino(dataset, nome_arquivo):
    """(tabela, extra) para um arquivo do manifesto, ou None se nao mapeado."""
    if nome_arquivo in DESTINO_POR_ARQUIVO:
        return DESTINO_POR_ARQUIVO[nome_arquivo]
    return DESTINO_POR_DATASET.get(dataset)

ROTULO_MODALIDADE = {
    "componentes-curriculares-presenciais.csv": "PRESENCIAL",
    "componentes-curriculares-semi-presenciais.csv": "SEMI_PRESENCIAL",
    "componentes-curriculares-ead.csv": "EAD",
}

# colunas que devem virar INTEGER / REAL mesmo que a amostra seja ambigua
FORCA_TEXTO = {
    "codigo_barras", "codigo", "codigo_turma", "codigo_curso", "codigo_inep",
    "isbn", "issn", "numero_diploma", "cpf", "sigla", "telefone",
    "num_processo_registro", "livro", "numero_folha", "dou",
    "codigo_area_conhecimento", "matricula_ou_siape", "matricula_docente_externo",
}

INT_RE = re.compile(r"^-?\d+$")
REAL_RE = re.compile(r"^-?\d+[.,]\d+$")


def tipo_da_coluna(nome, amostra):
    """Infere INTEGER/REAL/TEXT a partir de uma amostra de valores nao vazios."""
    if nome in FORCA_TEXTO:
        return "TEXT"
    vals = [v for v in amostra if v not in ("", None)][:800]
    if not vals:
        return "TEXT"
    if all(INT_RE.match(v) for v in vals):
        # ids de 19+ digitos estourariam o int64 do SQLite
        return "INTEGER" if all(len(v.lstrip("-")) <= 18 for v in vals) else "TEXT"
    if all(INT_RE.match(v) or REAL_RE.match(v) for v in vals):
        return "REAL"
    return "TEXT"


def normaliza(valor, tipo):
    """Converte a string crua do CSV para o que vai ao SQLite."""
    if valor is None:
        return None
    v = valor.strip()
    if v == "" or v.upper() in ("NULL", "NONE", "\\N"):
        return None
    if tipo == "REAL":
        v2 = v.replace(",", ".")
        try:
            return float(v2)
        except ValueError:
            return v
    if tipo == "INTEGER":
        try:
            return int(v)
        except ValueError:
            return v
    return v


def abre_csv(caminho):
    """Abre o CSV detectando encoding e separador."""
    bruto = caminho.read_bytes()[:200_000]
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            texto = bruto.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    primeira = texto.splitlines()[0] if texto.splitlines() else ""
    sep = max([";", ",", "\t", "|"], key=lambda s: primeira.count(s))
    if primeira.count(sep) == 0:
        sep = ";"
    return enc, sep


def ano_periodo(rotulo):
    """'Matriculas de 2026.1' -> ('2026.1', 2026, 1);  'Egressos de 2025' -> ('2025', 2025, None)"""
    m = re.search(r"((?:19|20)\d{2})(?:\.(\d))?", rotulo or "")
    if not m:
        return None, None, None
    ano = int(m.group(1))
    per = int(m.group(2)) if m.group(2) else None
    return (f"{ano}.{per}" if per else str(ano)), ano, per


def ident(nome):
    """Normaliza nome de coluna para identificador SQL seguro."""
    n = re.sub(r"[^0-9a-zA-Z_]", "_", (nome or "").strip()).strip("_").lower()
    return n or "col"


# ------------------------------------------------------------------ carregador

def carregar_csv(con, caminho, tabela, extra, rotulo, criadas):
    enc, sep = abre_csv(caminho)
    with open(caminho, encoding=enc, newline="", errors="replace") as f:
        leitor = csv.reader(f, delimiter=sep)
        cabecalho = next(leitor, None)
        if not cabecalho:
            return 0, 0
        colunas = [ident(c) for c in cabecalho]
        # desambigua colunas repetidas no mesmo arquivo
        vistas, finais = {}, []
        for c in colunas:
            vistas[c] = vistas.get(c, 0) + 1
            finais.append(c if vistas[c] == 1 else f"{c}_{vistas[c]}")
        colunas = finais

        # amostra para inferir tipos
        amostra, buffer = {c: [] for c in colunas}, []
        for linha in leitor:
            buffer.append(linha)
            for c, v in zip(colunas, linha):
                if len(amostra[c]) < 800:
                    amostra[c].append(v)
            if len(buffer) >= 3000:
                break

        tipos = {c: tipo_da_coluna(c, amostra[c]) for c in colunas}

        periodo_txt, ano, per = ano_periodo(rotulo)
        extras = []
        if extra == "periodo_arquivo":
            extras = [("periodo_referencia", "TEXT", periodo_txt),
                      ("ano_referencia", "INTEGER", ano),
                      ("semestre_referencia", "INTEGER", per)]
        elif extra == "origem_modalidade":
            extras = [("origem_modalidade", "TEXT", ROTULO_MODALIDADE[caminho.name])]

        if tabela not in criadas:
            defs = [f'"{c}" {tipos[c]}' for c in colunas]
            defs += [f'"{n}" {t}' for n, t, _ in extras]
            defs.append('"_fonte" TEXT')
            con.execute(f'CREATE TABLE "{tabela}" ({", ".join(defs)})')
            criadas[tabela] = colunas + [n for n, _, _ in extras] + ["_fonte"]

        col_tabela = criadas[tabela]
        # alinha as colunas do arquivo com as da tabela (datasets unificados
        # podem, em teoria, divergir; o que nao existir entra como NULL)
        todas = colunas + [n for n, _, _ in extras] + ["_fonte"]
        faltando = [c for c in todas if c not in col_tabela]
        for c in faltando:
            con.execute(f'ALTER TABLE "{tabela}" ADD COLUMN "{c}" '
                        f'{tipos.get(c, "TEXT")}')
            col_tabela.append(c)

        alvo = colunas + [n for n, _, _ in extras] + ["_fonte"]
        sql = (f'INSERT INTO "{tabela}" ({", ".join(chr(34) + c + chr(34) for c in alvo)}) '
               f'VALUES ({", ".join("?" * len(alvo))})')
        fixos = [v for _, _, v in extras] + [caminho.name]

        n_col = len(colunas)
        total, torto = 0, 0
        lote = []

        def processa(linha):
            nonlocal torto
            if len(linha) != n_col:
                torto += 1
                linha = (linha + [None] * n_col)[:n_col]
            return [normaliza(v, tipos[c]) for c, v in zip(colunas, linha)] + fixos

        for linha in buffer:
            lote.append(processa(linha))
        for linha in leitor:
            lote.append(processa(linha))
            if len(lote) >= 20_000:
                con.executemany(sql, lote)
                total += len(lote)
                lote = []
        if lote:
            con.executemany(sql, lote)
            total += len(lote)
        total += 0
        con.commit()
        return total, torto


def carregar_ps_outros(con, caminho):
    """Carrega processos-seletivos-outros.csv com o parser tolerante a HTML sujo.

    O CSV original tem aspas duplas nao escapadas no HTML dos editais; o leitor
    CSV padrao fragmenta um registro em dezenas de pedacos. Ver parser_tolerante.
    """
    con.execute("""
        CREATE TABLE processos_seletivos_outros (
            id_processo_seletivo INTEGER, processo_seletivo TEXT, id_curso INTEGER,
            nome_curso TEXT, inicio_inscricoes TEXT, fim_inscricoes TEXT,
            orientacoes_inscritos TEXT, nome TEXT, edital_html_bruto TEXT,
            vagas INTEGER, selecao_por_sorteio TEXT,
            parse_completo INTEGER, _fonte TEXT)
    """)
    texto = caminho.read_bytes().decode("utf-8-sig", errors="replace")
    corpo = texto[texto.index("\n") + 1:]

    cols = parser_tolerante.COLUNAS
    tipos = {"id_processo_seletivo": "INTEGER", "id_curso": "INTEGER", "vagas": "INTEGER"}
    lote, total, completos = [], 0, 0
    sql = (f"INSERT INTO processos_seletivos_outros "
           f"({', '.join(cols)}, parse_completo, _fonte) "
           f"VALUES ({', '.join('?' * (len(cols) + 2))})")

    for reg, ok in parser_tolerante.parse(corpo):
        lote.append([normaliza(reg.get(c), tipos.get(c, "TEXT")) for c in cols]
                    + [1 if ok else 0, caminho.name])
        completos += int(ok)
        if len(lote) >= 5000:
            con.executemany(sql, lote)
            total += len(lote)
            lote = []
    if lote:
        con.executemany(sql, lote)
        total += len(lote)
    con.commit()
    return total, total - completos


def carregar_pids(con, caminhos):
    """Normaliza o JSON dos PIDs em 'pids' (1 linha por docente/periodo) e
    'pid_turmas' (1 linha por turma do plano)."""
    con.executescript("""
        CREATE TABLE pids (
            siape INTEGER, docente TEXT, ano INTEGER, periodo INTEGER,
            ch_atendimento_aluno REAL, ch_atendimento_aluno_graduacao REAL,
            ch_atendimento_aluno_pos_graduacao REAL, ch_total_grupo_ensino REAL,
            ch_outras_atividades_ensino REAL, ch_extensao REAL, ch_pesquisa REAL,
            ch_funcoes_administrativas REAL, ch_outras_atividades REAL,
            outras_atividades_selecionadas TEXT,
            outras_atividades_especificadas TEXT,
            qtd_turmas INTEGER, _fonte TEXT
        );
        CREATE TABLE pid_turmas (
            siape INTEGER, ano INTEGER, periodo INTEGER,
            id_turma INTEGER, periodo_turma TEXT, nome TEXT, nivel_ensino TEXT,
            ch_total REAL, ch_dedicada_periodo REAL, _fonte TEXT
        );
    """)
    campos = ["siape", "docente", "ano", "periodo", "ch_atendimento_aluno",
              "ch_atendimento_aluno_graduacao", "ch_atendimento_aluno_pos_graduacao",
              "ch_total_grupo_ensino", "ch_outras_atividades_ensino", "ch_extensao",
              "ch_pesquisa", "ch_funcoes_administrativas", "ch_outras_atividades"]
    n_pid = n_turma = 0
    for caminho in caminhos:
        registros = json.load(open(caminho, encoding="utf-8"))
        linhas_pid, linhas_turma = [], []
        def escalar(v):
            """Campos como 'outras_atividades_*' as vezes vem como lista."""
            if isinstance(v, (list, dict)):
                return json.dumps(v, ensure_ascii=False)
            return v

        for reg in registros:
            turmas = reg.get("turmas_docente") or []
            linhas_pid.append(
                [escalar(reg.get(c)) for c in campos]
                + [escalar(reg.get("outras_atividades_selecionadas")),
                   escalar(reg.get("outras_atividades_especificadas")),
                   len(turmas), caminho.name])
            for t in turmas:
                linhas_turma.append([
                    escalar(reg.get("siape")), escalar(reg.get("ano")),
                    escalar(reg.get("periodo")),
                    escalar(t.get("id_turma")), escalar(t.get("periodo")),
                    escalar(t.get("nome")), escalar(t.get("nivel_ensino")),
                    escalar(t.get("ch_total")),
                    escalar(t.get("ch_dedicada_periodo")), caminho.name])
        con.executemany(
            f"INSERT INTO pids VALUES ({', '.join('?' * (len(campos) + 4))})", linhas_pid)
        con.executemany(
            "INSERT INTO pid_turmas VALUES (?,?,?,?,?,?,?,?,?,?)", linhas_turma)
        n_pid += len(linhas_pid)
        n_turma += len(linhas_turma)
        print(f"  pids/pid_turmas  <- {caminho.name}: "
              f"{len(linhas_pid)} planos, {len(linhas_turma)} turmas")
    con.commit()
    return n_pid, n_turma


# ------------------------------------------------------------------- indices

INDICES = [
    ("matriculas_componentes", ["id_turma"]), ("matriculas_componentes", ["id_curso"]),
    ("matriculas_componentes", ["discente"]),
    ("turmas", ["id_turma"]), ("turmas", ["siape"]),
    ("turmas", ["id_componente_curricular"]),
    ("turmas", ["matricula_docente_externo"]),
    ("cursos", ["id_curso"]), ("cursos_graduacao", ["id_curso"]),
    ("cursos_pos_graduacao", ["id_curso"]), ("cursos_tecnicos", ["id_curso"]),
    ("docentes", ["siape"]), ("docentes_externos", ["matricula_docente_externo"]),
    ("componentes_curriculares", ["id_componente"]),
    ("componentes_curriculares", ["codigo"]),
    ("estruturas_curriculares", ["id_curriculo"]),
    ("estruturas_curriculares", ["id_curso"]),
    ("curriculo_componente", ["id_curriculo"]),
    ("curriculo_componente", ["id_componente_curricular"]),
    ("discentes", ["matricula"]), ("discentes", ["id_curso"]),
    ("egressos", ["matricula"]), ("egressos", ["id_curso"]),
    ("situacoes_discentes", ["id_discente"]), ("situacoes_discentes", ["id_curso"]),
    ("avaliacoes_docencia", ["id_turma"]), ("avaliacoes_docencia", ["id_docente"]),
    ("orientacoes_docentes", ["id_docente"]),
    ("emprestimos", ["codigo_barras"]), ("emprestimos", ["matricula_ou_siape"]),
    ("acervo_exemplares", ["codigo_barras"]),
    ("acervo_exemplares", ["registro_sistema"]),
    ("acervo_titulos", ["registro_sistema"]),
    ("processos_seletivos_outros", ["id_curso"]),
    ("processos_seletivos_outros", ["id_processo_seletivo"]),
    ("processos_seletivos_graduacao", ["id_processo_seletivo"]),
    ("projetos_ensino", ["siape"]),
    ("pids", ["siape"]), ("pid_turmas", ["siape"]), ("pid_turmas", ["id_turma"]),
]


def corrigir_qualidade(con):
    """Correcoes de defeitos do dado de origem, medidas e documentadas.

    docentes_externos.matricula_docente_externo chega como '"10001"' -- com as
    aspas dentro do valor. Enquanto nao sao removidas, o join com turmas nao
    casa nenhuma matricula; depois da limpeza, casa praticamente todas
    (medido em quase 100% no historico completo de turmas).
    """
    antes = con.execute("""
        SELECT COUNT(*) FROM (SELECT DISTINCT matricula_docente_externo v FROM turmas
                              WHERE matricula_docente_externo IS NOT NULL) t
        WHERE EXISTS (SELECT 1 FROM docentes_externos d
                      WHERE d.matricula_docente_externo = t.v)""").fetchone()[0]
    con.execute("""UPDATE docentes_externos
                   SET matricula_docente_externo = TRIM(matricula_docente_externo, '"')
                   WHERE matricula_docente_externo LIKE '"%'""")
    con.commit()
    depois = con.execute("""
        SELECT COUNT(*) FROM (SELECT DISTINCT matricula_docente_externo v FROM turmas
                              WHERE matricula_docente_externo IS NOT NULL) t
        WHERE EXISTS (SELECT 1 FROM docentes_externos d
                      WHERE d.matricula_docente_externo = t.v)""").fetchone()[0]
    print(f"  docentes_externos: aspas removidas da matricula "
          f"(join com turmas: {antes} -> {depois})")

    # 7 componentes aparecem em dois arquivos de modalidade com a mesma ementa;
    # a duplicata faria o id_componente multiplicar linhas em todo join.
    dup = con.execute("""SELECT COUNT(*) - COUNT(DISTINCT id_componente)
                         FROM componentes_curriculares""").fetchone()[0]
    con.execute("""DELETE FROM componentes_curriculares WHERE rowid NOT IN
                   (SELECT MIN(rowid) FROM componentes_curriculares
                    GROUP BY id_componente)""")
    con.commit()
    print(f"  componentes_curriculares: {dup} linhas duplicadas por "
          f"id_componente removidas")


def criar_ponte_docentes(con):
    """Tabela de correspondencia entre os dois universos de id de docente.

    O portal usa dois identificadores diferentes e nunca os cruza:
      - siape       : docentes, turmas, pids, projetos_ensino
      - id_docente  : avaliacoes_docencia, orientacoes_docentes, id_coordenador
    projetos_ensino e a unica tabela que traz os dois lados na mesma linha, numa
    relacao 1:1 (1.450 pares). E a unica ponte possivel com os dados publicados.
    """
    con.execute("""
        CREATE TABLE docente_id_siape AS
        SELECT DISTINCT id_coordenador AS id_docente, siape
        FROM projetos_ensino
        WHERE siape IS NOT NULL AND id_coordenador IS NOT NULL""")
    con.execute("CREATE INDEX ix_ponte_id_docente ON docente_id_siape (id_docente)")
    con.execute("CREATE INDEX ix_ponte_siape ON docente_id_siape (siape)")
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM docente_id_siape").fetchone()[0]
    print(f"  docente_id_siape: {n:,} pares id_docente <-> siape")


def criar_ponte_egressos_por_nome(con):
    """Pontes por nome entre egressos e diplomas/tccs (sem id em comum).

    'egressos'/'discentes' identificam a pessoa por matricula real; 'diplomas'
    e 'tccs' nao tem nenhum id, so o NOME do formando em texto puro -- que e a
    unica coluna em comum com 'egressos.nome_discente'.

    Testado: casar por nome normalizado (UPPER+TRIM) acerta 91,8% dos egressos
    em diplomas e 75,6% em tccs. Mas 18,8% dos nomes em diplomas e 26,2% em
    tccs se repetem (homonimos) -- um join ingenuo atribuiria o diploma/TCC a
    pessoa errada numa fracao desses casos. Por isso a ponte so guarda pares
    onde o nome e UNICO nos dois lados (mesmo criterio de precisao usado em
    docente_id_siape): 69,4% dos egressos (diplomas) e 50,1% (tccs), sem risco
    de homonimo.
    """
    # Materializa nome normalizado + dados em tabelas temporarias indexadas
    # ANTES de juntar. Comparar "UPPER(TRIM(coluna_da_tabela_crua)) = X" no JOIN
    # final impede o uso de indice (SQLite teria que calcular a funcao linha a
    # linha nas 99.768/93.236 linhas de diplomas/tccs para cada probe), o que
    # trava a consulta por minutos. Com o nome ja calculado e indexado dos dois
    # lados, o join vira igualdade simples entre colunas indexadas.
    con.executescript("""
        CREATE TEMP TABLE _egressos_norm AS
            SELECT UPPER(TRIM(nome_discente)) AS nome, matricula, nome_discente
            FROM egressos WHERE nome_discente IS NOT NULL;
        CREATE INDEX _ix_en ON _egressos_norm(nome);

        CREATE TEMP TABLE _nome_unico_egressos AS
            SELECT nome FROM _egressos_norm GROUP BY nome HAVING COUNT(*) = 1;
        CREATE INDEX _ix_nue ON _nome_unico_egressos(nome);

        CREATE TEMP TABLE _diplomas_norm AS
            SELECT UPPER(TRIM(nome_discente)) AS nome, numero_diploma, titulacao,
                   data_conclusao, data_expedicao_diploma, curso
            FROM diplomas WHERE nome_discente IS NOT NULL;
        CREATE INDEX _ix_dn ON _diplomas_norm(nome);

        CREATE TEMP TABLE _nome_unico_diplomas AS
            SELECT nome FROM _diplomas_norm GROUP BY nome HAVING COUNT(*) = 1;
        CREATE INDEX _ix_nud ON _nome_unico_diplomas(nome);

        CREATE TEMP TABLE _tccs_norm AS
            SELECT UPPER(TRIM(nome_autor)) AS nome, titulo, nome_orientador,
                   curso, nivel, tipo_trabalho, data_defesa
            FROM tccs WHERE nome_autor IS NOT NULL;
        CREATE INDEX _ix_tn ON _tccs_norm(nome);

        CREATE TEMP TABLE _nome_unico_tccs AS
            SELECT nome FROM _tccs_norm GROUP BY nome HAVING COUNT(*) = 1;
        CREATE INDEX _ix_nut ON _nome_unico_tccs(nome);

        CREATE TABLE egresso_diploma AS
        SELECT en.matricula, en.nome_discente,
               dn.numero_diploma, dn.titulacao, dn.data_conclusao,
               dn.data_expedicao_diploma, dn.curso AS curso_diploma
        FROM _egressos_norm en
        JOIN _nome_unico_egressos ue ON ue.nome = en.nome
        JOIN _nome_unico_diplomas ud ON ud.nome = en.nome
        JOIN _diplomas_norm dn       ON dn.nome = en.nome;

        CREATE TABLE egresso_tcc AS
        SELECT en.matricula, en.nome_discente,
               tn.titulo, tn.nome_orientador, tn.curso AS curso_tcc,
               tn.nivel, tn.tipo_trabalho, tn.data_defesa
        FROM _egressos_norm en
        JOIN _nome_unico_egressos ue ON ue.nome = en.nome
        JOIN _nome_unico_tccs ut     ON ut.nome = en.nome
        JOIN _tccs_norm tn           ON tn.nome = en.nome;

        DROP TABLE _egressos_norm;
        DROP TABLE _nome_unico_egressos;
        DROP TABLE _diplomas_norm;
        DROP TABLE _nome_unico_diplomas;
        DROP TABLE _tccs_norm;
        DROP TABLE _nome_unico_tccs;
    """)
    con.execute("CREATE INDEX ix_egresso_diploma_matricula ON egresso_diploma (matricula)")
    con.execute("CREATE INDEX ix_egresso_tcc_matricula ON egresso_tcc (matricula)")
    con.commit()
    n1 = con.execute("SELECT COUNT(*) FROM egresso_diploma").fetchone()[0]
    n2 = con.execute("SELECT COUNT(*) FROM egresso_tcc").fetchone()[0]
    tot = con.execute("SELECT COUNT(*) FROM egressos").fetchone()[0]
    print(f"  egresso_diploma: {n1:,} pares por nome unico "
          f"({n1/tot*100:.1f}% dos {tot:,} egressos)")
    print(f"  egresso_tcc: {n2:,} pares por nome unico "
          f"({n2/tot*100:.1f}% dos {tot:,} egressos)")


VIEWS = {
    # ATENCAO A GRANULARIDADE: 'turmas' tem uma linha por turma-DOCENTE, nao por
    # turma (ha turmas com ate ~90 docentes, fan-out medio de ~1,6x no historico
    # completo). 'avaliacoes_docencia' tem uma linha por docente avaliado na
    # turma. Juntar direto com matriculas multiplicaria as linhas no mesmo fator.
    # As views abaixo primeiro colapsam para 1 linha por turma e so depois juntam.

    # uma linha por id_turma, com os docentes agregados
    "vw_turma_info": """
        SELECT t.id_turma,
               MIN(t.codigo_turma)   AS codigo_turma,
               MIN(t.ano)            AS ano,
               MIN(t.periodo)        AS periodo,
               MIN(t.nivel_ensino)   AS nivel_ensino,
               MIN(t.campus_turma)   AS campus_turma,
               MIN(t.local)          AS local,
               MIN(t.descricao_horario) AS descricao_horario,
               MIN(t.capacidade_aluno)  AS capacidade_aluno,
               MIN(t.total_solicitacoes) AS total_solicitacoes,
               MIN(t.situacao_turma) AS situacao_turma,
               MIN(t.tipo)           AS tipo,
               MIN(t.id_componente_curricular) AS id_componente_curricular,
               COUNT(DISTINCT t.siape) AS qtd_docentes_internos,
               COUNT(DISTINCT t.matricula_docente_externo) AS qtd_docentes_externos,
               GROUP_CONCAT(DISTINCT t.siape) AS siapes
        FROM turmas t
        GROUP BY t.id_turma""",

    # uma linha por turma/semestre com as medias da avaliacao de docencia
    "vw_avaliacao_turma": """
        SELECT id_turma, ano, periodo,
               COUNT(DISTINCT id_docente) AS qtd_docentes_avaliados,
               SUM(qtd_discentes)         AS qtd_discentes_respondentes,
               ROUND(AVG(postura_profissional_media), 3) AS postura_media,
               ROUND(AVG(atuacao_profissional_media), 3) AS atuacao_media,
               ROUND(AVG(autoavaliacao_aluno_media), 3)  AS autoavaliacao_media
        FROM avaliacoes_docencia
        GROUP BY id_turma, ano, periodo""",

    # relacao turma <-> docente (a granularidade natural de 'turmas')
    "vw_turma_docente": """
        SELECT t.id_turma, t.ano, t.periodo, t.siape,
               t.matricula_docente_externo,
               COALESCE(d.nome, de.nome) AS nome_docente,
               CASE WHEN d.siape IS NOT NULL THEN 'INTERNO'
                    WHEN de.matricula_docente_externo IS NOT NULL THEN 'EXTERNO'
                    ELSE 'NAO_IDENTIFICADO' END AS vinculo_docente,
               d.categoria, d.lotacao, d.formacao,
               de.instituicao_ensino AS instituicao_externa,
               t.ch_dedicada_periodo
        FROM turmas t
        LEFT JOIN docentes d  ON d.siape = t.siape
        LEFT JOIN docentes_externos de
               ON de.matricula_docente_externo = t.matricula_docente_externo""",

    # 1 linha por matricula (sem fan-out), com turma, componente e curso
    "vw_matriculas_completa": """
        SELECT m.periodo_referencia, m.ano_referencia, m.semestre_referencia,
               m.id_turma, m.discente AS discente_hash, m.nota, m.media_final,
               m.numero_total_faltas, m.descricao AS situacao_matricula,
               ti.codigo_turma, ti.nivel_ensino, ti.campus_turma,
               ti.situacao_turma, ti.qtd_docentes_internos, ti.siapes,
               ti.id_componente_curricular,
               cc.codigo AS codigo_componente, cc.nome AS nome_componente,
               cc.ch_total AS ch_componente, cc.unidade_responsavel,
               m.id_curso, c.nome AS nome_curso, c.grau_academico, c.municipio
        FROM matriculas_componentes m
        JOIN vw_turma_info ti ON ti.id_turma = m.id_turma
        LEFT JOIN componentes_curriculares cc
               ON cc.id_componente = ti.id_componente_curricular
        LEFT JOIN cursos c ON c.id_curso = m.id_curso""",

    # 1 linha por turma, com componente, contagem de matriculas e avaliacao
    "vw_turmas_completa": """
        SELECT ti.id_turma, ti.codigo_turma, ti.ano, ti.periodo, ti.nivel_ensino,
               ti.campus_turma, ti.local, ti.capacidade_aluno,
               ti.total_solicitacoes, ti.situacao_turma, ti.descricao_horario,
               ti.qtd_docentes_internos, ti.qtd_docentes_externos, ti.siapes,
               cc.codigo AS codigo_componente, cc.nome AS nome_componente,
               cc.ch_total AS ch_componente, cc.modalidade,
               cc.unidade_responsavel,
               av.qtd_docentes_avaliados, av.qtd_discentes_respondentes,
               av.postura_media, av.atuacao_media, av.autoavaliacao_media,
               (SELECT COUNT(*) FROM matriculas_componentes m
                WHERE m.id_turma = ti.id_turma) AS qtd_matriculas
        FROM vw_turma_info ti
        LEFT JOIN componentes_curriculares cc
               ON cc.id_componente = ti.id_componente_curricular
        LEFT JOIN vw_avaliacao_turma av
               ON av.id_turma = ti.id_turma AND av.ano = ti.ano
              AND av.periodo = ti.periodo""",

    # trajetoria do discente anonimizado: matriculas + situacao, ligadas pelo hash
    "vw_discente_hash": """
        SELECT s.id_discente AS discente_hash, s.ano_ingresso, s.periodo_ingresso,
               s.nivel_ensino, s.id_curso, s.curso, s.situacao,
               s.periodo_referencia,
               (SELECT COUNT(*) FROM matriculas_componentes m
                WHERE m.discente = s.id_discente) AS qtd_matriculas,
               (SELECT ROUND(AVG(m.media_final), 2) FROM matriculas_componentes m
                WHERE m.discente = s.id_discente AND m.media_final IS NOT NULL)
                   AS media_geral
        FROM situacoes_discentes s""",

    # egresso enriquecido com diploma/TCC resolvidos pela ponte por nome.
    # qtd_matriculas/media_geral ficam NULL: egressos nao tem hash em comum com
    # matriculas_componentes (ver "Limites conhecidos" no README).
    "vw_egressos_completo": """
        SELECT e.matricula, e.nome_discente, e.sexo, e.ano_ingresso,
               e.periodo_ingresso, e.ano_conclusao, e.periodo_conclusao,
               e.id_curso, e.nome_curso, e.modalidade_educacao,
               e.forma_ingresso, e.nivel_ensino,
               ed.numero_diploma, ed.titulacao, ed.data_expedicao_diploma,
               et.titulo AS titulo_tcc, et.nome_orientador AS orientador_tcc,
               et.data_defesa AS data_defesa_tcc
        FROM egressos e
        LEFT JOIN egresso_diploma ed ON ed.matricula = e.matricula
        LEFT JOIN egresso_tcc et     ON et.matricula = e.matricula""",

    # avaliacao de docencia com o siape resolvido pela ponte (quando possivel)
    "vw_avaliacoes_docencia": """
        SELECT av.ano, av.periodo, av.id_turma, av.id_docente,
               av.nome_docente, p.siape, d.categoria, d.lotacao,
               av.qtd_discentes, av.postura_profissional_media,
               av.atuacao_profissional_media, av.autoavaliacao_aluno_media,
               t.codigo_turma, cc.nome AS nome_componente
        FROM avaliacoes_docencia av
        LEFT JOIN docente_id_siape p ON p.id_docente = av.id_docente
        LEFT JOIN docentes d         ON d.siape = p.siape
        LEFT JOIN vw_turma_info t    ON t.id_turma = av.id_turma
        LEFT JOIN componentes_curriculares cc
               ON cc.id_componente = t.id_componente_curricular""",

    # emprestimo com o titulo do acervo resolvido.
    # codigo_barras repete em ~1.385 exemplares (dado sujo na origem), por isso
    # o acervo e colapsado antes do join, mantendo 1 linha por codigo_barras.
    "vw_emprestimos_acervo": """
        SELECT e.id_emprestimo, e.periodo_referencia, e.data_emprestimo,
               e.data_devolucao, e.data_renovacao, e.tipo_vinculo_usuario,
               e.codigo_barras, ex.biblioteca, ex.colecao, ex.status_material,
               ex.localizacao, at.titulo, at.autor, at.assunto,
               at.tipo_material, at.ano AS ano_publicacao, at.editora, at.isbn
        FROM emprestimos e
        LEFT JOIN (SELECT codigo_barras,
                          MIN(registro_sistema) AS registro_sistema,
                          MIN(biblioteca)       AS biblioteca,
                          MIN(colecao)          AS colecao,
                          MIN(status_material)  AS status_material,
                          MIN(localizacao)      AS localizacao
                   FROM acervo_exemplares GROUP BY codigo_barras) ex
               ON ex.codigo_barras = e.codigo_barras
        LEFT JOIN acervo_titulos at ON at.registro_sistema = ex.registro_sistema""",

    # estrutura curricular com seus componentes
    "vw_estrutura_componentes": """
        SELECT ec.id_curriculo, ec.codigo AS codigo_curriculo, ec.nome_matriz,
               ec.id_curso, ec.nome_curso, ec.ano_entrada_vigor,
               ec.ch_total_minima, ec.cr_total_minimo,
               cp.semestre_oferta, cp.tipo_vinculo_componente,
               cc.codigo AS codigo_componente, cc.nome AS nome_componente,
               cc.ch_total AS ch_componente, cc.nivel
        FROM estruturas_curriculares ec
        JOIN curriculo_componente cp ON cp.id_curriculo = ec.id_curriculo
        LEFT JOIN componentes_curriculares cc
               ON cc.id_componente = cp.id_componente_curricular""",
}


def criar_views(con):
    for nome, sql in VIEWS.items():
        con.execute(f"CREATE VIEW {nome} AS {sql}")
    con.commit()
    print(f"  {len(VIEWS)} views criadas: {', '.join(VIEWS)}")


def main():
    if BANCO.exists():
        BANCO.unlink()

    manifesto = json.load(open(RAIZ / "manifesto.json", encoding="utf-8"))
    con = sqlite3.connect(BANCO)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")

    criadas, resumo, pulados = {}, [], []
    pids_json = []

    print("Carregando arquivos...\n")
    for item in sorted(manifesto, key=lambda i: i["arquivo"]):
        caminho = RAIZ / item["arquivo"]
        if not caminho.exists():
            pulados.append((item["arquivo"], "arquivo ausente"))
            continue
        if item["formato"] == "JSON":
            pids_json.append(caminho)
            continue
        if caminho.name == "processos-seletivos-outros.csv":
            n, incompletos = carregar_ps_outros(con, caminho)
            aviso = f"  ({incompletos} registros so com id + html bruto)" if incompletos else ""
            print(f"  {'processos_seletivos_outros':<32} <- {caminho.name:<48} "
                  f"{n:>8} linhas{aviso}")
            resumo.append(("processos_seletivos_outros", caminho.name, n))
            continue
        destino = resolver_destino(item["dataset"], caminho.name)
        if destino is None:
            pulados.append((caminho.name, "sem destino mapeado"))
            continue
        tabela, extra = destino
        n, torto = carregar_csv(con, caminho, tabela, extra, item["recurso"], criadas)
        aviso = f"  ({torto} linhas com nº de campos divergente)" if torto else ""
        print(f"  {tabela:<32} <- {caminho.name:<48} {n:>8} linhas{aviso}")
        resumo.append((tabela, caminho.name, n))

    if pids_json:
        carregar_pids(con, sorted(pids_json))

    # tabela de procedencia: liga cada tabela ao recurso/URL de origem
    con.execute("""CREATE TABLE _fontes (
        tabela TEXT, dataset TEXT, dataset_titulo TEXT, recurso TEXT,
        ano_selecionado INTEGER, formato TEXT, arquivo TEXT, url TEXT, bytes INTEGER)""")
    for item in manifesto:
        nome = Path(item["arquivo"]).name
        if item["formato"] == "JSON":
            tabela = "pids / pid_turmas"
        elif nome == "processos-seletivos-outros.csv":
            tabela = "processos_seletivos_outros"
        else:
            destino = resolver_destino(item["dataset"], nome)
            tabela = destino[0] if destino else "(nao carregado)"
        con.execute("INSERT INTO _fontes VALUES (?,?,?,?,?,?,?,?,?)",
                    (tabela, item["dataset"], item["dataset_titulo"], item["recurso"],
                     item["ano_selecionado"], item["formato"], item["arquivo"],
                     item["url"], item["bytes"]))
    con.commit()

    print("\nCriando indices...")
    feitos = 0
    for tabela, cols in INDICES:
        existe = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabela,)).fetchone()
        if not existe:
            continue
        presentes = {r[1] for r in con.execute(f'PRAGMA table_info("{tabela}")')}
        if not set(cols) <= presentes:
            print(f"  ! {tabela}({', '.join(cols)}): coluna inexistente, indice ignorado")
            continue
        nome = f"ix_{tabela}__{'_'.join(cols)}"
        con.execute(f'CREATE INDEX "{nome}" ON "{tabela}" ({", ".join(cols)})')
        feitos += 1
    con.commit()
    print(f"  {feitos} indices criados")

    print("\nCorrigindo defeitos do dado de origem...")
    corrigir_qualidade(con)

    print("\nCriando ponte entre identificadores de docente...")
    criar_ponte_docentes(con)

    print("\nCriando ponte entre egressos e diplomas/tccs (por nome)...")
    criar_ponte_egressos_por_nome(con)

    print("\nCriando views de consulta...")
    criar_views(con)

    print("\nANALYZE + VACUUM...")
    con.execute("ANALYZE")
    con.commit()
    con.execute("VACUUM")
    con.close()

    print(f"\n{'=' * 78}")
    tabelas = sqlite3.connect(BANCO).execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    print(f"Banco: {BANCO.name}  ({BANCO.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"Tabelas: {len(tabelas)}")
    if pulados:
        print(f"\nArquivos nao carregados ({len(pulados)}):")
        for a, m in pulados:
            print(f"  {a}: {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
