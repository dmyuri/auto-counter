"""Estado da sessão em curso, em `sessao_atual.json` — T-08.

Comportamento em `.spec/features/interface-sessao/spec.md`: AC-012.1 (minutos
capturados e perdidos até ali), AC-012.2 (a fase e o progresso dentro dela) e
AC-012.4 (o progresso é reencontrado ao reabrir a interface).

Quem grava é o processo da sessão (`session run`); a interface só lê. O arquivo
existe à parte do `manifest.json` de propósito: no Windows, um leitor com o
manifest aberto faz o `os.replace` da captura falhar, e a captura cairia por
causa de uma tela. Aqui, a gravação é atômica (temporário + `os.replace`) e
**best-effort**: se falhar, tenta de novo algumas vezes e desiste em silêncio até
a próxima atualização. O progresso nunca derruba a captura nem o processamento.

O arquivo **fica** depois do fim da sessão, para a interface mostrar o resultado
da última sessão ao ser reaberta. Estado em fase não terminal sem uma trava viva
do mesmo `pid` significa que o processo morreu sem concluir; quem decide isso é
a leitura (T-13), não este módulo.

Por `acompanhamento-ao-vivo` (SUP-058), o arquivo também carrega as quantidades
de veículos já contados por categoria (`quantidades`, `null` na captura) e o
instante do desfecho (`terminada_em`, `null` até terminar). O total não é
gravado: é a soma das quatro categorias, calculada por quem lê (SUP-054).

Por `layout-interface` (SUP-069, SUP-070), o arquivo também carrega o instante Tm
em que o minuto em análise começou a ser processado (`minuto_em_analise_desde`)
e, para a taxa, quantos minutos já concluíram com dado (`minutos_com_dado`) e os
veículos aceitos nesses minutos (`veiculos_nos_minutos_com_dado`). Arquivo de
versão anterior não tem os três campos e é lido com `None`, 0 e 0.
"""

import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from auto_counter.counting.config import Categoria

NOME_DO_ESTADO = "sessao_atual.json"
"""Nome do arquivo dentro do diretório de dados (D-9)."""

TENTATIVAS_DE_GRAVACAO = 5
ESPERA_ENTRE_TENTATIVAS = 0.05
"""No Windows, trocar um arquivo que um leitor tem aberto levanta
`PermissionError` por instantes; algumas tentativas curtas bastam."""


class Fase(Enum):
    """Onde a sessão está.

    A persistência e a exportação contam como fim do `PROCESSAMENTO`, porque
    AC-012.2 fala em duas fases só.
    """

    CAPTURA = "CAPTURA"
    PROCESSAMENTO = "PROCESSAMENTO"
    CONCLUIDA = "CONCLUIDA"
    SEM_PLANILHA = "SEM_PLANILHA"
    PROCESSAMENTO_CANCELADO = "PROCESSAMENTO_CANCELADO"
    FALHOU = "FALHOU"

    @property
    def terminal(self) -> bool:
        return self not in (Fase.CAPTURA, Fase.PROCESSAMENTO)


@dataclass(frozen=True)
class EstadoDaSessao:
    """O que `sessao_atual.json` registra."""

    pid: int
    id_camera: str
    nome_camera: str | None
    duracao_pedida: int
    iniciada_em: datetime
    fase: Fase
    minutos_capturados: tuple[int, ...] = ()
    minutos_perdidos: tuple[int, ...] = ()
    minutos_a_processar: int = 0
    minutos_processados: int = 0
    id_sessao: str | None = None
    status: str | None = None
    planilha: str | None = None
    mensagem: str | None = None
    quantidades: dict[str, int] | None = None
    """Veículos contados por categoria, chaveados por `Categoria.value` (D-4).
    `None` durante a captura (SUP-055); zeros a partir do processamento."""
    terminada_em: datetime | None = None
    """Instante UTC do desfecho; `None` até `terminar`."""
    minuto_em_analise_desde: datetime | None = None
    """Tm (SUP-070): instante UTC em que o minuto em análise começou a ser
    processado. `None` na captura."""
    minutos_com_dado: int = 0
    """k (SUP-069): minutos já concluídos com dado, sem os descartados."""
    veiculos_nos_minutos_com_dado: int = 0
    """V (SUP-069): veículos aceitos nesses k minutos."""


def _em_utc(instante: datetime) -> datetime:
    """Normaliza para UTC ciente de fuso.

    Sem `tzinfo` não há como saber se o valor já era UTC, e assumir seria
    inventar hora — mesma recusa de `capture/manifest.py` e
    `storage/sessions.py`.
    """
    if instante.tzinfo is None:
        raise ValueError(
            f"instante sem fuso horário ({instante!r}); o estado da sessão é "
            f"gravado em UTC com fuso explícito, e um datetime ingênuo não diz "
            f"qual é o dele"
        )
    return instante.astimezone(timezone.utc)


def _caminho(data_dir: str | Path) -> Path:
    return Path(data_dir) / NOME_DO_ESTADO


def _como_dicionario(estado: EstadoDaSessao) -> dict:
    return {
        "pid": estado.pid,
        "id_camera": estado.id_camera,
        "nome_camera": estado.nome_camera,
        "duracao_pedida": estado.duracao_pedida,
        "iniciada_em": _em_utc(estado.iniciada_em).isoformat(),
        "fase": estado.fase.value,
        "minutos_capturados": list(estado.minutos_capturados),
        "minutos_perdidos": list(estado.minutos_perdidos),
        "minutos_a_processar": estado.minutos_a_processar,
        "minutos_processados": estado.minutos_processados,
        "id_sessao": estado.id_sessao,
        "status": estado.status,
        "planilha": estado.planilha,
        "mensagem": estado.mensagem,
        "quantidades": (
            None if estado.quantidades is None else dict(estado.quantidades)
        ),
        "terminada_em": (
            None
            if estado.terminada_em is None
            else _em_utc(estado.terminada_em).isoformat()
        ),
        "minuto_em_analise_desde": (
            None
            if estado.minuto_em_analise_desde is None
            else _em_utc(estado.minuto_em_analise_desde).isoformat()
        ),
        "minutos_com_dado": estado.minutos_com_dado,
        "veiculos_nos_minutos_com_dado": estado.veiculos_nos_minutos_com_dado,
    }


def _ler_quantidades(bruto) -> dict[str, int] | None:
    if bruto is None:
        return None
    return {categoria.value: int(bruto[categoria.value]) for categoria in Categoria}


def ler_estado(data_dir: str | Path) -> EstadoDaSessao | None:
    """O estado gravado, ou `None` se não existe ou não pôde ser lido.

    Nunca levanta: quem lê é a interface, que pode estar no meio de uma troca do
    arquivo, e uma tela não pode cair por isso.
    """
    try:
        dados = json.loads(_caminho(data_dir).read_text(encoding="utf-8"))
        return EstadoDaSessao(
            pid=int(dados["pid"]),
            id_camera=str(dados["id_camera"]),
            nome_camera=dados["nome_camera"],
            duracao_pedida=int(dados["duracao_pedida"]),
            iniciada_em=_em_utc(datetime.fromisoformat(dados["iniciada_em"])),
            fase=Fase(dados["fase"]),
            minutos_capturados=tuple(int(m) for m in dados["minutos_capturados"]),
            minutos_perdidos=tuple(int(m) for m in dados["minutos_perdidos"]),
            minutos_a_processar=int(dados["minutos_a_processar"]),
            minutos_processados=int(dados["minutos_processados"]),
            id_sessao=dados["id_sessao"],
            status=dados["status"],
            planilha=dados["planilha"],
            mensagem=dados["mensagem"],
            # Arquivo de versão anterior não tem os dois campos: valem `None`.
            quantidades=_ler_quantidades(dados.get("quantidades")),
            terminada_em=(
                None
                if dados.get("terminada_em") is None
                else _em_utc(datetime.fromisoformat(dados["terminada_em"]))
            ),
            # Arquivo de versão anterior não tem os três campos abaixo.
            minuto_em_analise_desde=(
                None
                if dados.get("minuto_em_analise_desde") is None
                else _em_utc(datetime.fromisoformat(dados["minuto_em_analise_desde"]))
            ),
            minutos_com_dado=int(dados.get("minutos_com_dado", 0)),
            veiculos_nos_minutos_com_dado=int(
                dados.get("veiculos_nos_minutos_com_dado", 0)
            ),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


class AnotadorDoEstado:
    """Mantém o `sessao_atual.json` da sessão que este processo está rodando.

    Cada método regrava o arquivo inteiro. Nenhum levanta por falha de disco
    (D-9): o progresso é conveniência, e a sessão vale mais que a tela.
    """

    def __init__(
        self,
        data_dir: str | Path,
        *,
        pid: int,
        id_camera: str,
        nome_camera: str | None,
        duracao_pedida: int,
        iniciada_em: datetime,
        agora: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._data_dir = Path(data_dir)
        self._agora = agora
        # Quanto de cada categoria veio do minuto em curso (D-5). Só em
        # memória: se o processo morrer, a sessão termina sem resultado.
        self._do_minuto: dict[str, int] = {}
        # O minuto em curso foi descartado? (D-3) Só em memória.
        self._minuto_descartado = False
        self._estado = EstadoDaSessao(
            pid=pid,
            id_camera=id_camera,
            nome_camera=nome_camera,
            duracao_pedida=duracao_pedida,
            iniciada_em=_em_utc(iniciada_em),
            fase=Fase.CAPTURA,
        )

    @property
    def estado(self) -> EstadoDaSessao:
        return self._estado

    def iniciar(self) -> None:
        """Grava o estado inicial, na fase de captura."""
        self._gravar()

    def minuto_da_captura(self, minuto: int, capturado: bool) -> None:
        """Acumula um minuto resolvido na captura (AC-012.1)."""
        if capturado:
            self._estado = replace(
                self._estado,
                minutos_capturados=(*self._estado.minutos_capturados, minuto),
            )
        else:
            self._estado = replace(
                self._estado,
                minutos_perdidos=(*self._estado.minutos_perdidos, minuto),
            )
        self._gravar()

    def processamento_iniciado(self, id_sessao: str, a_processar: int) -> None:
        """Passa à fase de processamento (AC-012.2)."""
        self._estado = replace(
            self._estado,
            fase=Fase.PROCESSAMENTO,
            id_sessao=id_sessao,
            minutos_a_processar=a_processar,
            minutos_processados=0,
            quantidades={categoria.value: 0 for categoria in Categoria},
        )
        self._do_minuto = {}
        self._minuto_descartado = False
        self._gravar()

    def minuto_iniciado(self) -> None:
        """Grava Tm: o minuto em análise começa a ser processado (SUP-070)."""
        self._minuto_descartado = False
        self._estado = replace(
            self._estado, minuto_em_analise_desde=_em_utc(self._agora())
        )
        self._gravar()

    def evento_aceito(self, minuto: int, categoria: Categoria) -> None:
        """Soma um veículo à categoria e ao acumulador do minuto (AC-016.2)."""
        quantidades = dict(self._estado.quantidades or {})
        chave = categoria.value
        quantidades[chave] = quantidades.get(chave, 0) + 1
        self._do_minuto[chave] = self._do_minuto.get(chave, 0) + 1
        self._estado = replace(self._estado, quantidades=quantidades)
        self._gravar()

    def minuto_descartado(self, minuto: int) -> None:
        """Desconta o que o minuto em curso tinha somado (AC-016.8, SUP-061)."""
        quantidades = dict(self._estado.quantidades or {})
        for chave, quantos in self._do_minuto.items():
            quantidades[chave] = quantidades.get(chave, 0) - quantos
        self._do_minuto = {}
        self._minuto_descartado = True
        self._estado = replace(self._estado, quantidades=quantidades)
        self._gravar()

    def minuto_processado(self) -> None:
        """Conta mais um minuto analisado (AC-012.2); o minuto vira definitivo.

        Minuto com dado entra em k e em V; minuto descartado, não (SUP-069).
        """
        self._do_minuto = {}
        mudancas = {"minutos_processados": self._estado.minutos_processados + 1}
        if not self._minuto_descartado:
            mudancas["minutos_com_dado"] = self._estado.minutos_com_dado + 1
            mudancas["veiculos_nos_minutos_com_dado"] = sum(
                (self._estado.quantidades or {}).values()
            )
        self._minuto_descartado = False
        self._estado = replace(self._estado, **mudancas)
        self._gravar()

    def terminar(
        self,
        fase: Fase,
        *,
        id_sessao: str | None = None,
        status: str | None = None,
        planilha: str | None = None,
        mensagem: str | None = None,
    ) -> None:
        """Grava o desfecho. O arquivo fica depois do fim da sessão."""
        if not fase.terminal:
            raise ValueError(f"{fase.value} não é uma fase terminal")
        self._estado = replace(
            self._estado,
            fase=fase,
            id_sessao=id_sessao if id_sessao is not None else self._estado.id_sessao,
            status=status,
            planilha=planilha,
            mensagem=mensagem,
            terminada_em=_em_utc(self._agora()),
        )
        if not self._gravar():
            print(
                f"aviso: não foi possível gravar o desfecho da sessão em "
                f"{_caminho(self._data_dir)}; a interface pode não mostrá-lo",
                file=sys.stderr,
            )

    def _gravar(self) -> bool:
        """Grava de forma atômica; devolve se conseguiu. Nunca levanta."""
        caminho = _caminho(self._data_dir)
        temporario = caminho.with_name(f"{caminho.name}.{os.getpid()}.tmp")
        conteudo = json.dumps(
            _como_dicionario(self._estado), ensure_ascii=False, indent=2
        )
        for tentativa in range(TENTATIVAS_DE_GRAVACAO):
            try:
                caminho.parent.mkdir(parents=True, exist_ok=True)
                temporario.write_text(conteudo + "\n", encoding="utf-8")
                os.replace(temporario, caminho)
                return True
            except OSError:
                temporario.unlink(missing_ok=True)
                if tentativa < TENTATIVAS_DE_GRAVACAO - 1:
                    time.sleep(ESPERA_ENTRE_TENTATIVAS)
        return False
