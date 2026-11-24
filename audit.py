#!/usr/bin/env python3
"""Gate de rastreabilidade: confere se cada critério de aceite ativo
tem um teste que passou.

Uso: pytest --junitxml=report.xml && python audit.py

Critérios marcados como REVOGADO ou SUBSTITUÍDO permanecem na spec como
histórico, mas não são exigidos — o comportamento deixou de existir.
"""

import re, sys, glob
import xml.etree.ElementTree as ET

SPECS      = ".spec/features/**/spec.md"
RELATORIOS = "report.xml"

ID_NA_SPEC  = re.compile(r"AC-(\d+)\.(\d+)")        # AC-001.1
ID_NO_TESTE = re.compile(r"AC[-_](\d+)[-_](\d+)")   # test_AC_001_1_...
INATIVO     = re.compile(r"REVOGADO|SUBSTITU[IÍ]DO", re.I)
PENDENCIA   = re.compile(r"^\s*-\s*\[ \]\s*(SUP|Q)-", re.M)


def normaliza(m):
    """AC-1.1, AC-001.1 e AC_001_1 viram todos AC-001.1"""
    return f"AC-{int(m.group(1)):03d}.{int(m.group(2))}"


def criterios_ativos(caminho):
    """IDs exigíveis de uma spec.

    Linhas com REVOGADO ou SUBSTITUÍDO são ignoradas — isso cobre tanto
    a marcação do critério inativo quanto as notas que citam IDs de
    outras specs, que não devem ser exigidos aqui.
    """
    ativos = set()
    for linha in open(caminho, encoding="utf-8"):
        if INATIVO.search(linha):
            continue
        ativos |= {normaliza(m) for m in ID_NA_SPEC.finditer(linha)}
    return ativos


falhas = []

# 1. Critérios ativos declarados nas specs
declarados = set()
for caminho in glob.glob(SPECS, recursive=True):
    declarados |= criterios_ativos(caminho)

# 2. Critérios com teste que realmente passou
provados, marcados = set(), set()
arquivos = glob.glob(RELATORIOS, recursive=True)

if not arquivos:
    print(f"ERRO: nenhum relatório encontrado em '{RELATORIOS}'. "
          f"Rode os testes com saída JUnit XML antes do gate.")
    sys.exit(2)

for arquivo in arquivos:
    for tc in ET.parse(arquivo).getroot().iter("testcase"):
        nome = f"{tc.get('classname', '')} {tc.get('name', '')}"
        acs = {normaliza(m) for m in ID_NO_TESTE.finditer(nome)}
        marcados |= acs
        passou = not any(tc.find(t) is not None
                         for t in ("failure", "error", "skipped"))
        if passou:
            provados |= acs

# 3. Cruzamento nas duas direções
for ac in sorted(declarados - provados):
    falhas.append(f"SEM PROVA:    {ac} — sem teste, ou o teste falhou ou foi pulado")

for ac in sorted(marcados - declarados):
    falhas.append(f"TESTE ÓRFÃO:  {ac} — não existe, foi revogado ou foi substituído")

# 4. Pendências em aberto
for caminho in glob.glob(SPECS, recursive=True):
    if PENDENCIA.search(open(caminho, encoding="utf-8").read()):
        falhas.append(f"PENDÊNCIA:    {caminho} — suposição ou pergunta sem resposta")

if falhas:
    print("\n".join(falhas))
    print(f"\n{len(falhas)} problema(s). "
          f"{len(declarados)} critério(s) ativo(s), {len(provados)} provado(s).")
    sys.exit(1)

print(f"OK — {len(declarados)} critério(s) ativo(s), todos provados.")
sys.exit(0)