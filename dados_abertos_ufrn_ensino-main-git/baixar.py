"""
Baixa os dados do grupo 'ensino' do portal de dados abertos da UFRN.

Regra de selecao por dataset (ver RECORTE):
  - "max"          -> so o ano/semestre mais recente (comportamento padrao).
  - ("desde", ano) -> todo ano >= o indicado, com todos os semestres.
  - "tudo"         -> historico completo disponivel no portal.
  - Dataset sem recorte temporal (nome sem ano) -> baixa todos os recursos
    de qualquer forma (tabelas de dimensao/cadastro).
  - PDFs (dicionarios de dados) -> baixa todos, em pasta separada.

Saida:
  arquivos/dados/<dataset>/<arquivo>
  arquivos/dicionarios/<dataset>__<arquivo>.pdf
  manifesto.json   (metadados de tudo que foi baixado)
"""
import json
import re
import sys
import time
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://dados.ufrn.br/api/3/action"
GRUPO = "ensino"
RAIZ = Path(__file__).parent
DIR_DADOS = RAIZ / "arquivos" / "dados"
DIR_DIC = RAIZ / "arquivos" / "dicionarios"

ANO_RE = re.compile(r"(19|20)\d{2}")

# Profundidade historica por dataset. Datasets fora deste dict usam "max"
# (comportamento padrao: so o ano/semestre mais recente).
#
# "tudo" baixa o historico completo disponivel no portal -- usado na maioria,
# pois destrava conexoes entre anos que antes nao se cruzavam (ex.: turmas e
# avaliacoes_docencia so casavam numa fracao minima quando turmas tinha so 1
# ano; com o historico completo, passam a casar na faixa de 90%+).
# 'matriculas-componentes' e a exceccao: e a maior tabela do banco (ja soma
# ~15M linhas so na janela abaixo) e o historico completo do portal (42
# arquivos, 2007-2026) e quase o dobro do que foi baixado. Optou-se por uma
# janela de 10 anos (2016-2026), que cobre toda a sobreposicao real com
# 'turmas' (disponivel 2000-2025) sem o salto de volume do historico completo.
RECORTE = {
    "matriculas-componentes": ("desde", 2016),
    "turmas": "tudo",
    "emprestimos-acervos-das-bibliotecas": "tudo",
    "discentes": "tudo",
    "egressos": "tudo",
    "situacoes-de-discentes": "tudo",
    "orientacoes-docentes": "tudo",
    "planos-individuais-docentes": "tudo",
}

S = requests.Session()
S.verify = False  # o portal serve uma cadeia de certificados incompleta
S.headers["User-Agent"] = "Mozilla/5.0 (pesquisa-academica; coleta de dados abertos UFRN)"


def api(action, **params):
    r = S.get(f"{BASE}/{action}", params=params, timeout=120)
    r.raise_for_status()
    return r.json()["result"]


def ano_de(rotulo):
    """Extrai o ano do nome do recurso, ou None se o recurso for atemporal."""
    m = ANO_RE.search(rotulo or "")
    return int(m.group(0)) if m else None


def nome_arquivo(recurso, dataset):
    """Nome de arquivo seguro, derivado da URL (que ja traz a extensao correta)."""
    bruto = recurso["url"].rstrip("/").split("/")[-1]
    bruto = re.sub(r"[^A-Za-z0-9._-]", "_", bruto) or f"{dataset}.dat"
    fmt = (recurso.get("format") or "").lower()
    if fmt and "." not in bruto:
        bruto = f"{bruto}.{fmt}"
    return bruto


def selecionar(pkg):
    """Devolve (recursos_de_dados_escolhidos, pdfs, anos_escolhidos)."""
    dados, pdfs = [], []
    for r in pkg["resources"]:
        if (r.get("format") or "").upper() == "PDF":
            pdfs.append(r)
        else:
            dados.append(r)

    anos = [a for a in (ano_de(r.get("name")) for r in dados) if a]
    if not anos:
        return dados, pdfs, None  # dataset atemporal: leva tudo

    regra = RECORTE.get(pkg["name"], "max")
    if regra == "tudo":
        desejados = set(anos)
    elif isinstance(regra, tuple) and regra[0] == "desde":
        desejados = {a for a in anos if a >= regra[1]}
    else:  # "max"
        desejados = {max(anos)}

    escolhidos = [r for r in dados if ano_de(r.get("name")) in desejados]
    return escolhidos, pdfs, sorted(desejados, reverse=True)


def baixar(url, destino, tentativas=4):
    """Baixa com streaming. Pula se o destino ja existe e nao esta vazio."""
    if destino.exists() and destino.stat().st_size > 0:
        return destino.stat().st_size, "cache"

    parcial = destino.with_suffix(destino.suffix + ".parcial")
    for tentativa in range(1, tentativas + 1):
        try:
            with S.get(url, stream=True, timeout=(30, 600)) as r:
                r.raise_for_status()
                bytes_escritos = 0
                with open(parcial, "wb") as f:
                    for bloco in r.iter_content(chunk_size=1024 * 256):
                        if bloco:
                            f.write(bloco)
                            bytes_escritos += len(bloco)
            if bytes_escritos == 0:
                raise IOError("resposta vazia")
            parcial.replace(destino)
            return bytes_escritos, "ok"
        except Exception as e:
            if parcial.exists():
                parcial.unlink()
            if tentativa == tentativas:
                return 0, f"ERRO: {e.__class__.__name__}: {e}"
            time.sleep(3 * tentativa)


def mb(n):
    return f"{n / 1024 / 1024:8.2f} MB"


def main():
    DIR_DADOS.mkdir(parents=True, exist_ok=True)
    DIR_DIC.mkdir(parents=True, exist_ok=True)

    grupo = api("group_show", id=GRUPO, include_datasets="true")
    nomes = [p["name"] for p in grupo["packages"]]
    print(f"Grupo '{GRUPO}': {len(nomes)} datasets\n")

    manifesto = []
    total_bytes = 0
    falhas = []

    for i, nome in enumerate(nomes, 1):
        pkg = api("package_show", id=nome)
        escolhidos, pdfs, anos = selecionar(pkg)
        if not anos:
            marca = "atemporal"
        elif len(anos) > 6:
            marca = f"anos {min(anos)}..{max(anos)} ({len(anos)} anos)"
        else:
            marca = "ano " + "+".join(str(a) for a in anos)
        print(f"[{i:>2}/{len(nomes)}] {nome}  ({marca})  "
              f"{len(escolhidos)} dado(s) + {len(pdfs)} pdf(s)")

        pasta = DIR_DADOS / nome
        pasta.mkdir(parents=True, exist_ok=True)

        for r in escolhidos:
            arq = pasta / nome_arquivo(r, nome)
            n, status = baixar(r["url"], arq)
            total_bytes += n
            print(f"         {mb(n)}  {status:<6} {arq.name}")
            if status.startswith("ERRO"):
                falhas.append((nome, r.get("name"), r["url"], status))
                continue
            manifesto.append({
                "dataset": nome,
                "dataset_titulo": pkg["title"],
                "recurso": r.get("name"),
                "ano_selecionado": ano_de(r.get("name")),
                "formato": (r.get("format") or "").upper(),
                "url": r["url"],
                "arquivo": str(arq.relative_to(RAIZ)).replace("\\", "/"),
                "bytes": arq.stat().st_size,
            })

        for r in pdfs:
            arq = DIR_DIC / f"{nome}__{nome_arquivo(r, nome)}"
            n, status = baixar(r["url"], arq)
            total_bytes += n
            if status.startswith("ERRO"):
                falhas.append((nome, r.get("name"), r["url"], status))

    with open(RAIZ / "manifesto.json", "w", encoding="utf-8") as f:
        json.dump(manifesto, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 70}")
    print(f"Arquivos de dados baixados: {len(manifesto)}")
    print(f"Volume total: {total_bytes / 1024 / 1024:.1f} MB")
    print(f"Manifesto: manifesto.json")
    if falhas:
        print(f"\nFALHAS ({len(falhas)}):")
        for d, rec, url, st in falhas:
            print(f"  {d} / {rec}: {st}")
        return 1
    print("Nenhuma falha.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
