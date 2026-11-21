"""
Parser para processos-seletivos-outros.csv, que traz HTML de editais (colado do
Word) com aspas duplas NAO escapadas e quebras de linha dentro dos campos.
Nenhum parser CSV convencional le esse arquivo corretamente.

Estrategia:
  1. Cada registro comeca com '"<digitos>";' no inicio de uma linha. Isso ancora
     a segmentacao dos registros, imune ao HTML multi-linha do meio.
  2. Dentro do registro, os 8 primeiros campos (ids, datas, nome do edital) e os
     2 ultimos (vagas, selecao_por_sorteio) sao limpos e saem por regex.
  3. Os 2 campos do meio sao HTML de edital e nao ha delimitador confiavel entre
     eles; ficam preservados juntos na coluna 'edital_html_bruto'.
"""
import re

COLUNAS = [
    "id_processo_seletivo", "processo_seletivo", "id_curso", "nome_curso",
    "inicio_inscricoes", "fim_inscricoes", "orientacoes_inscritos", "nome",
    "edital_html_bruto", "vagas", "selecao_por_sorteio",
]

ANCORA = re.compile(r'(?m)^"(\d+)";')
# 8 primeiros campos: nenhum deles contem aspas nos registros bem formados
ESQUERDA = re.compile(
    r'^"(\d+)";"([^"]*)";"([^"]*)";"([^"]*)";"([^"]*)";"([^"]*)";"([^"]*)";"([^"]*)";'
)
# os dois ultimos campos: vagas (numero) e selecao_por_sorteio (true/false)
DIREITA = re.compile(r';"(\d*)";"(true|false)";?\s*$', re.I)


def parse(texto):
    """Gera (registro, ok) onde registro e um dict e ok indica parse completo."""
    inicios = [m.start() for m in ANCORA.finditer(texto)]
    for k, ini in enumerate(inicios):
        fim = inicios[k + 1] if k + 1 < len(inicios) else len(texto)
        bruto = texto[ini:fim].rstrip("\r\n")

        m_esq = ESQUERDA.match(bruto)
        m_dir = DIREITA.search(bruto)
        if not m_esq:
            # registro fora do padrao: guarda so o id ancorado
            id_ps = ANCORA.match(bruto).group(1)
            yield ({"id_processo_seletivo": id_ps, "edital_html_bruto": bruto}, False)
            continue

        reg = dict(zip(COLUNAS[:8], m_esq.groups()))
        if m_dir:
            reg["vagas"] = m_dir.group(1)
            reg["selecao_por_sorteio"] = m_dir.group(2).lower()
            meio = bruto[m_esq.end():m_dir.start()]
        else:
            reg["vagas"] = None
            reg["selecao_por_sorteio"] = None
            meio = bruto[m_esq.end():]
        # tira as aspas externas do bloco HTML
        reg["edital_html_bruto"] = meio.strip().strip('"')
        yield (reg, bool(m_dir))


if __name__ == "__main__":
    from collections import Counter
    from pathlib import Path

    caminho = (Path(__file__).parent
               / "arquivos/dados/processos-seletivos/processos-seletivos-outros.csv")
    texto = caminho.read_bytes().decode("utf-8-sig", errors="replace")
    corpo = texto[texto.index("\n") + 1:]

    regs = list(parse(corpo))
    print(f"registros recuperados      : {len(regs):,}")
    print(f"com parse completo (8+2)   : {sum(1 for _, ok in regs if ok):,}")
    print(f"com cabeca reconhecida     : "
          f"{sum(1 for r, _ in regs if 'nome_curso' in r):,}")

    print("\n--- sanidade dos campos estruturados ---")
    for col in ("id_processo_seletivo", "id_curso", "vagas"):
        c = Counter("numerico" if (r.get(col) or "").strip().isdigit()
                    else ("vazio" if not (r.get(col) or "").strip() else "OUTRO")
                    for r, _ in regs)
        print(f"  {col:<24} {dict(c)}")
    c = Counter((r.get("selecao_por_sorteio") or "(nulo)") for r, _ in regs)
    print(f"  {'selecao_por_sorteio':<24} {dict(c)}")

    print("\n--- 6 primeiros registros ---")
    for r, ok in regs[:6]:
        print(f"  [{'ok' if ok else '??'}] id={r.get('id_processo_seletivo'):<8} "
              f"id_curso={str(r.get('id_curso')):<10} "
              f"curso={str(r.get('nome_curso'))[:30]:<32} "
              f"vagas={str(r.get('vagas')):<5} html={len(r.get('edital_html_bruto') or ''):>6}c")

    print("\n--- exemplos de nome_curso (deve ser texto de curso, nunca HTML) ---")
    nomes = [r.get("nome_curso") for r, _ in regs if (r.get("nome_curso") or "").strip()]
    for n in nomes[:8]:
        print(f"    {n[:70]!r}")
    suspeitos = [n for n in nomes if "<" in n or "style=" in n]
    print(f"\n  nome_curso contendo HTML: {len(suspeitos)} de {len(nomes)}")
