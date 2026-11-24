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

Por `download-clipes` (SUP-080), o arquivo também carrega a escolha de manter
os vídeos feita ao iniciar (`manter_videos`) e, só no desfecho `CONCLUIDA` com
essa escolha ligada, a lista dos clipes capturados (`clipes`). Quem conhece os
clipes é o processo da sessão, não a interface: é por isso que eles entram
aqui, em vez de a tela abrir o `manifest.json` (D-9). Arquivo de versão
anterior não tem os dois campos e é lido com `False` e `None`.

Por `processamento-upload` (D-11), o arquivo também carrega a origem da sessão
(`origem`, `CAMERA` ou `UPLOAD`) e, no upload, o estado de cada vídeo
(`videos`). Arquivo de versão anterior é lido com `"CAMERA"` e `()`.

Por `servidor-indisponivel` (D-10), o arquivo também carrega a marca de captura
encerrada por servidor indisponível (`encerrada_por_servidor_indisponivel`) e o
instante da primeira falha da sequência que levou ao encerramento
(`servidor_indisponivel_desde`). Arquivo de versão anterior é lido com `False` e
`None`. Não há fase nova: o desfecho continua `CONCLUIDA` ou `SEM_PLANILHA`.
"""

import json
import os
import sys
import time
from collections.abc import Callable, Sequence
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


class SituacaoDoVideo(Enum):
    """O estado de um vídeo da sessão de upload (AC-028.3, SUP-089)."""

    FILA = "FILA"
    PROCESSANDO = "PROCESSANDO"
    CONCLUIDO = "CONCLUIDO"
    FALHOU = "FALHOU"
    INTERROMPIDO = "INTERROMPIDO"


@dataclass(frozen=True)
class VideoNoEstado:
    """Um vídeo da sessão de upload, pelo nome original e pela situação."""

    nome: str
    situacao: SituacaoDoVideo


MENSAGEM_SESSAO_CANCELADA = "Sessão cancelada pelo usuário"
"""AC-012.7: o que a interface mostra quando o usuário para a captura. Vive aqui
para `pipeline/run.py` gravar e `ui/app.py` importar, sem repetir o texto."""


class Fase(Enum):
    """Onde a sessão está.

    A persistência e a exportação contam como fim do `PROCESSAMENTO`, porque
    AC-012.2 fala em duas fases só.

    `SESSAO_CANCELADA` (AC-012.7) é o desfecho de quem parou na captura pela
    interface: nada foi contado e os clipes foram apagados. É distinto de
    `PROCESSAMENTO_CANCELADO`, que mantém os vídeos para reprocessar.
    """

    CAPTURA = "CAPTURA"
    PROCESSAMENTO = "PROCESSAMENTO"
    CONCLUIDA = "CONCLUIDA"
    SEM_PLANILHA = "SEM_PLANILHA"
    PROCESSAMENTO_CANCELADO = "PROCESSAMENTO_CANCELADO"
    SESSAO_CANCELADA = "SESSAO_CANCELADA"
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
    manter_videos: bool = False
    """A escolha feita ao iniciar (SUP-080, D-1)."""
    clipes: "tuple[ClipeMantido, ...] | None" = None
    """Só no desfecho `CONCLUIDA` com `manter_videos` (D-1); `None` até lá."""
    origem: str = "CAMERA"
    """`CAMERA` ou `UPLOAD` (processamento-upload, D-11)."""
    videos: tuple[VideoNoEstado, ...] = ()
    """Só no upload: os vídeos na ordem da lista, com a situação de cada um."""
    encerrada_por_servidor_indisponivel: bool = False
    """AC-033.5: a captura acabou porque o servidor ficou indisponível."""
    servidor_indisponivel_desde: datetime | None = None
    """Instante UTC da primeira falha da sequência que levou ao encerramento."""


@dataclass(frozen=True)
class ClipeMantido:
    """Um clipe capturado, gravado no desfecho `CONCLUIDA` (download-clipes, D-1)."""

    minuto: int
    caminho: Path
    last_modified: datetime
    duracao_segundos: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "last_modified", _em_utc(self.last_modified))


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
        "manter_videos": estado.manter_videos,
        "clipes": (
            None
            if estado.clipes is None
            else [
                {
                    "minuto": clipe.minuto,
                    "caminho": str(clipe.caminho),
                    "last_modified": clipe.last_modified.isoformat(),
                    "duracao_segundos": clipe.duracao_segundos,
                }
                for clipe in estado.clipes
            ]
        ),
        "origem": estado.origem,
        "videos": [
            {"nome": video.nome, "situacao": video.situacao.value}
            for video in estado.videos
        ],
        "encerrada_por_servidor_indisponivel": (
            estado.encerrada_por_servidor_indisponivel
        ),
        "servidor_indisponivel_desde": (
            None
            if estado.servidor_indisponivel_desde is None
            else _em_utc(estado.servidor_indisponivel_desde).isoformat()
        ),
    }


def _ler_quantidades(bruto) -> dict[str, int] | None:
    if bruto is None:
        return None
    return {categoria.value: int(bruto[categoria.value]) for categoria in Categoria}


def _ler_clipes(bruto) -> "tuple[ClipeMantido, ...] | None":
    if bruto is None:
        return None
    return tuple(
        ClipeMantido(
            minuto=int(item["minuto"]),
            caminho=Path(item["caminho"]),
            last_modified=datetime.fromisoformat(item["last_modified"]),
            duracao_segundos=(
                None
                if item["duracao_segundos"] is None
                else int(item["duracao_segundos"])
            ),
        )
        for item in bruto
    )


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
            # Arquivo de versão anterior não tem os dois campos abaixo
            # (download-clipes, SUP-080): valem `False` e `None`.
            manter_videos=bool(dados.get("manter_videos", False)),
            clipes=_ler_clipes(dados.get("clipes")),
            # Arquivo de versão anterior não tem os dois campos abaixo
            # (processamento-upload, D-11): valem "CAMERA" e `()`.
            origem=str(dados.get("origem", "CAMERA")),
            videos=tuple(
                VideoNoEstado(
                    nome=str(item["nome"]),
                    situacao=SituacaoDoVideo(item["situacao"]),
                )
                for item in dados.get("videos", [])
            ),
            # Arquivo de versão anterior não tem os dois campos abaixo
            # (servidor-indisponivel, D-10): valem `False` e `None`.
            encerrada_por_servidor_indisponivel=bool(
                dados.get("encerrada_por_servidor_indisponivel", False)
            ),
            servidor_indisponivel_desde=(
                None
                if dados.get("servidor_indisponivel_desde") is None
                else _em_utc(
                    datetime.fromisoformat(dados["servidor_indisponivel_desde"])
                )
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
        manter_videos: bool = False,
        origem: str = "CAMERA",
        videos: Sequence[str] = (),
    ) -> None:
        self._data_dir = Path(data_dir)
        self._agora = agora
        # Quanto de cada categoria veio do minuto em curso (D-5). Só em
        # memória: se o processo morrer, a sessão termina sem resultado.
        self._do_minuto: dict[str, int] = {}
        # O minuto em curso foi descartado? (D-3) Só em memória.
        self._minuto_descartado = False
        if origem == "UPLOAD":
            # A sessão de upload nasce no processamento, sem captura (D-11).
            self._estado = EstadoDaSessao(
                pid=pid,
                id_camera=id_camera,
                nome_camera=nome_camera,
                duracao_pedida=duracao_pedida,
                iniciada_em=_em_utc(iniciada_em),
                fase=Fase.PROCESSAMENTO,
                minutos_a_processar=duracao_pedida,
                quantidades={categoria.value: 0 for categoria in Categoria},
                origem=origem,
                videos=tuple(
                    VideoNoEstado(nome, SituacaoDoVideo.FILA) for nome in videos
                ),
            )
            return
        self._estado = EstadoDaSessao(
            pid=pid,
            id_camera=id_camera,
            nome_camera=nome_camera,
            duracao_pedida=duracao_pedida,
            iniciada_em=_em_utc(iniciada_em),
            fase=Fase.CAPTURA,
            manter_videos=manter_videos,
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

    def captura_encerrada_por_servidor(self, desde: datetime) -> None:
        """Marca a captura como encerrada por servidor indisponível (AC-033.5).

        `desde` é o instante da primeira falha da sequência ininterrupta que
        levou ao encerramento (SUP-129). A fase não muda (D-10).
        """
        self._estado = replace(
            self._estado,
            encerrada_por_servidor_indisponivel=True,
            servidor_indisponivel_desde=_em_utc(desde),
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

    def minuto_sem_dado(self) -> None:
        """Conta um minuto resolvido sem dado (AC-028.9, AC-016.8).

        Soma em `minutos_processados` e não em `minutos_com_dado` nem em V.
        """
        self._do_minuto = {}
        self._minuto_descartado = False
        self._estado = replace(
            self._estado, minutos_processados=self._estado.minutos_processados + 1
        )
        self._gravar()

    def video_iniciado(self, posicao: int) -> None:
        """Marca o vídeo como `PROCESSANDO`; no máximo um por vez (AC-028.3)."""
        if any(
            video.situacao is SituacaoDoVideo.PROCESSANDO
            for video in self._estado.videos
        ):
            raise ValueError(
                f"já há um vídeo em processamento; o vídeo {posicao} não pode "
                f"começar (AC-028.3)"
            )
        self._situacao_do_video(posicao, SituacaoDoVideo.PROCESSANDO)

    def video_terminado(self, posicao: int, situacao: SituacaoDoVideo) -> None:
        """Grava o desfecho do vídeo: concluído, falhou ou interrompido."""
        if situacao not in (
            SituacaoDoVideo.CONCLUIDO,
            SituacaoDoVideo.FALHOU,
            SituacaoDoVideo.INTERROMPIDO,
        ):
            raise ValueError(f"{situacao.value} não é um desfecho de vídeo")
        self._situacao_do_video(posicao, situacao)

    def _situacao_do_video(self, posicao: int, situacao: SituacaoDoVideo) -> None:
        if not 1 <= posicao <= len(self._estado.videos):
            raise ValueError(
                f"vídeo {posicao} fora da lista de {len(self._estado.videos)}"
            )
        videos = list(self._estado.videos)
        videos[posicao - 1] = replace(videos[posicao - 1], situacao=situacao)
        self._estado = replace(self._estado, videos=tuple(videos))
        self._gravar()

    def terminar(
        self,
        fase: Fase,
        *,
        id_sessao: str | None = None,
        status: str | None = None,
        planilha: str | None = None,
        mensagem: str | None = None,
        clipes: "tuple[ClipeMantido, ...] | None" = None,
    ) -> None:
        """Grava o desfecho. O arquivo fica depois do fim da sessão.

        Quem decide se há clipes é quem chama (`executar_sessao`, T-04); este
        método só grava o que recebe.
        """
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
            clipes=clipes,
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
