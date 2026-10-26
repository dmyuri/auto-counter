"""Relatório em texto da validação (AC-015.1, SUP-049, D-11).

Texto puro em UTF-8, sem cor ANSI e com tabelas de largura fixa: legível sem
ferramenta especial, para poder ser citado no TCC. Toda linha, exceto a da data
e hora da execução, é função só do resultado (AC-014.5).
"""

from datetime import datetime, timezone
from pathlib import Path

from auto_counter.counting.config import Categoria
from auto_counter.validation.model import ClipeMedido, Condicao, ResultadoDaValidacao
from auto_counter.validation.pairing import JANELA_DE_PAREAMENTO_EM_SEGUNDOS
from auto_counter.validation.verdict import (
    ACERTO_MINIMO_PERCENTUAL,
    ERRO_MAXIMO_PERCENTUAL,
    _linha,
    _percentual,
    mensagem_de_falha,
)

_FORMATO_DO_NOME = "%Y%m%dT%H%M%SZ"
_SUBDIRETORIO = "validacao"


def _em_utc(instante: datetime) -> datetime:
    if instante.tzinfo is None:
        raise ValueError(
            f"instante sem fuso horário ({instante!r}); o relatório é datado em "
            f"UTC, e um datetime ingênuo não diz qual é o dele"
        )
    return instante.astimezone(timezone.utc)


def _cabecalho(resultado: ResultadoDaValidacao, executado_em: datetime) -> list[str]:
    config = resultado.configuracao
    return [
        "RELATÓRIO DE VALIDAÇÃO DE ACURÁCIA",
        f"Executado em (UTC): {_em_utc(executado_em):%Y-%m-%dT%H:%M:%SZ}",
        f"Versão do modelo: {resultado.versao_do_modelo}",
        f"Limiar de confiança: {config.limiar_de_confianca}",
        f"Amostragem: 1 frame a cada {config.amostragem}",
        f"Tamanho de entrada: {config.tamanho_de_entrada}",
        f"Limite do erro de contagem: ≤ {ERRO_MAXIMO_PERCENTUAL}% em cada sentido",
        f"Limite do acerto de categoria: ≥ {ACERTO_MINIMO_PERCENTUAL}%",
        f"Janela de pareamento: {JANELA_DE_PAREAMENTO_EM_SEGUNDOS} s",
    ]


def _corpo_do_clipe(medido: ClipeMedido) -> list[str]:
    clipe = medido.clipe
    camera = medido.camera
    linha = camera.linha
    linhas = [
        f"Câmera: {camera.id} ({camera.nome})",
        f"Linha de contagem: de ({linha.p1.x}, {linha.p1.y}) a ({linha.p2.x}, {linha.p2.y})",
        f"Sentidos: {camera.sentido_a}, {camera.sentido_b}",
        f"Last-Modified: {clipe.last_modified.isoformat()}",
        f"ETag: {clipe.etag}",
        f"sha256 do vídeo: {medido.sha256_video or 'não calculado'}",
        f"sha256 do CSV: {medido.sha256_csv or 'não calculado'}",
    ]
    medicao = medido.medicao
    if medicao is None:
        linhas.append(f"Medição: não medido — {medido.motivo_nao_medido}")
        return linhas

    largura = max(8, *(len(e.sentido) for e in medicao.erros))
    linhas += [
        "",
        f"{'Sentido':<{largura}}  {'Manual':>6}  {'Automático':>10}  Erro",
    ]
    for erro in medicao.erros:
        diferenca = abs(erro.automatico - erro.manual)
        if erro.erro is None:
            texto = f"indefinido (manual {erro.manual}, automático {erro.automatico})"
        elif erro.manual == 0:
            texto = "0.00% (0/0)"
        else:
            texto = f"{_percentual(diferenca, erro.manual)} ({diferenca}/{erro.manual})"
        linhas.append(
            f"{erro.sentido:<{largura}}  {erro.manual:>6}  {erro.automatico:>10}  {texto}"
        )

    acerto = medicao.acerto
    if acerto.fracao is None:
        texto_acerto = "indefinido (0 pares)"
    else:
        texto_acerto = (
            f"{_percentual(acerto.acertos, acerto.pares)} "
            f"({acerto.acertos}/{acerto.pares})"
        )
    pareamento = medicao.pareamento
    linhas += [
        "",
        f"Pares: {acerto.pares}, acertos de categoria: {acerto.acertos}",
        f"Acerto de categoria: {texto_acerto}",
        f"Veículos sem par — manuais: {len(pareamento.manuais_sem_par)}, "
        f"automáticos: {len(pareamento.automaticos_sem_par)}",
        "",
        "Matriz de confusão (linhas = manual, colunas = automático):",
    ]
    nomes = [c.value for c in Categoria]
    colunas = max(len(nome) for nome in nomes)
    linhas.append("  " + " " * colunas + "".join(f"  {nome:>{colunas}}" for nome in nomes))
    for nome, celulas in zip(nomes, medicao.matriz.linhas):
        linhas.append(
            "  " + f"{nome:<{colunas}}" + "".join(f"  {c:>{colunas}}" for c in celulas)
        )
    return linhas


def montar_relatorio(
    resultado: ResultadoDaValidacao, *, executado_em: datetime
) -> str:
    """Monta o texto do relatório. Função pura: não lê disco nem relógio."""
    linhas = _cabecalho(resultado, executado_em)

    for medido in resultado.clipes:
        condicao = medido.clipe.condicao
        if not condicao.obrigatoria:
            continue
        linhas += ["", f"=== Clipe {condicao.value} ===", *_corpo_do_clipe(medido), ""]
        veredito = medido.veredito
        linhas.append(
            f"Veredito do clipe {condicao.value}: "
            f"{'APROVADO' if veredito.passou else 'REPROVADO'}"
        )
        linhas.extend(_linha(violacao) for violacao in veredito.violacoes)

    for medido in resultado.clipes:
        if medido.clipe.condicao is not Condicao.CHUVA:
            continue
        linhas += [
            "",
            "=== Clipe chuva — medição fora da meta, que não entra no veredito ===",
            *_corpo_do_clipe(medido),
        ]
        if medido.veredito is not None:
            linhas += [
                "",
                "Atende aos limites (informativo): "
                f"{'sim' if medido.veredito.passou else 'não'}",
            ]
            linhas.extend(_linha(violacao) for violacao in medido.veredito.violacoes)

    conjunto = resultado.veredito
    linhas += [
        "",
        f"VEREDITO DO CONJUNTO: {'APROVADO' if conjunto.passou else 'REPROVADO'}",
    ]
    if not conjunto.passou:
        linhas.append(mensagem_de_falha(conjunto))
    return "\n".join(linhas) + "\n"


def gravar_relatorio(
    texto: str, *, data_dir: str | Path, executado_em: datetime
) -> Path:
    """Grava `<data_dir>/validacao/relatorio-<AAAAMMDDTHHMMSSZ>.txt`.

    Abre com modo `"x"`: um arquivo existente nunca é sobrescrito, porque duas
    execuções só são comparáveis se as duas deixarem rastro (D-11).
    """
    diretorio = Path(data_dir) / _SUBDIRETORIO
    diretorio.mkdir(parents=True, exist_ok=True)
    nome = f"relatorio-{_em_utc(executado_em).strftime(_FORMATO_DO_NOME)}.txt"
    caminho = diretorio / nome
    try:
        with caminho.open("x", encoding="utf-8", newline="\n") as arquivo:
            arquivo.write(texto)
    except FileExistsError as falha:
        raise FileExistsError(
            f"o relatório {caminho} já existe e não é sobrescrito"
        ) from falha
    return caminho
