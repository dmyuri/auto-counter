"""Manifest da sessão em disco: a prova durável de que os clipes existem.

Comportamento em `.spec/features/captura-clipes/spec.md`:

- AC-003.1 — cada clipe fica associado ao seu número de minuto, ao seu ETag e
  ao seu Last-Modified, e uma sessão de N minutos sem falhas tem N clipes
  **distintos** em disco;
- AC-003.4 — início e fim do período da sessão vêm do Last-Modified do primeiro
  e do último clipe **efetivamente capturados**, nunca do relógio local no
  início do comando.

Implementa SUP-009 (a referência de tempo é o Last-Modified do servidor; o
relógio local é gravado à parte, apenas como diagnóstico) e SUP-012 (os clipes
ficam em `<data_dir>/sessions/<id_sessao>/`).

O arquivo existe por D-3 do `_tasks.md`: o registro de sessão de AC-008.1 é da
feature `persistencia-resultados`, que ainda não existe, e sem o manifest
AC-003.1 ficaria sem prova durável e os clipes preservados por `--keep-clips`
chegariam ao ground truth sem ETag nem Last-Modified. Quando
`persistencia-resultados` for implementada, é ela quem lê este arquivo e grava
no SQLite — **o manifest não é banco paralelo**, e por isso a função de leitura
`ler` faz parte da entrega desta tarefa, junto com `contagem-veiculos` e T-09
entre os consumidores previstos.

O manifest **não é arquivo de vídeo**: o descarte de AC-003.5 apaga os `.mp4` e
deixa este arquivo no lugar, porque é nele que vivem o status e a lista de
minutos perdidos de que AC-007.4 e AC-008.4 dependem.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from auto_counter.capture.status import ResultadoDoStatus, StatusDaSessao

NOME_DO_MANIFEST = "manifest.json"
"""Nome do arquivo dentro do diretório da sessão (D-3)."""

SUBDIRETORIO_DE_SESSOES = "sessions"
"""Onde as sessões caem dentro do `data_dir` (SUP-012)."""

FORMATO_DO_ID_DE_SESSAO = "%Y%m%dT%H%M%SZ"
"""Carimbo de tempo do id de sessão, no formato de D-5 (`AAAAMMDDTHHMMSSZ`)."""

VERSAO_DO_MANIFEST = 3
"""Versão do formato gravado.

`persistencia-resultados` vai ler este arquivo; sem um número de versão, uma
mudança futura de formato seria indistinguível de um arquivo corrompido.

Subiu de 1 para 2 quando o `sha256` do clipe entrou na entrada de minuto
(SUP-051): schema já commitado é imutável (`CLAUDE.md`), então campo novo é
versão nova. Manifests versão 1 continuam sendo lidos — neles o `sha256` é
nulo, porque não foi registrado.

Subiu de 2 para 3 quando a marca de encerramento por servidor indisponível e o
instante da queda entraram no topo (AC-033.5, AC-036.2, D-7 de
`servidor-indisponivel`). Manifests versão 1 e 2 continuam sendo lidos, com a
marca `False` e o instante nulo.
"""


def id_da_sessao(id_camera: str, instante: datetime) -> str:
    """Monta o id da sessão no formato de D-5: `<id_camera>-<AAAAMMDDTHHMMSSZ>`.

    `instante` é o relógio local no momento do comando, e este id é **nome de
    diretório e nada mais**: ele não é a referência de tempo da sessão, que vem
    do Last-Modified dos clipes (AC-003.4 e SUP-009). Nenhuma spec fixa este
    formato — se `persistencia-resultados` precisar de outro, é aqui que muda.
    """
    return f"{id_camera}-{instante.astimezone(timezone.utc):{FORMATO_DO_ID_DE_SESSAO}}"


def diretorio_da_sessao(data_dir: str | Path, id_sessao: str) -> Path:
    """Caminho da sessão: `<data_dir>/sessions/<id_sessao>/` (SUP-012).

    O `data_dir` chega por parâmetro; quem resolve `AUTO_COUNTER_DATA_DIR` é o
    CLI (T-10), reusando `VARIAVEL_DATA_DIR` e `DATA_DIR_PADRAO` de
    `auto_counter.cli`. Esta função só monta o caminho, não cria nada.
    """
    return Path(data_dir) / SUBDIRETORIO_DE_SESSOES / id_sessao


def nome_do_arquivo_do_minuto(minuto: int) -> str:
    """Nome do clipe do minuto `minuto`, com padding: `minuto-03.mp4`.

    O padding é o que faz a ordem alfabética do diretório ser a ordem da
    sessão — sem ele, `minuto-10.mp4` viria antes de `minuto-2.mp4` e a leitura
    manual do material capturado sairia fora de ordem.
    """
    return f"minuto-{minuto:02d}.mp4"


def _em_utc(instante: datetime) -> datetime:
    """Normaliza para UTC ciente de fuso, como exige a serialização.

    Um `datetime` ingênuo aqui viraria um ISO 8601 sem fuso, e SUP-030 de
    `persistencia-resultados` — que vai ler este arquivo — exige o fuso
    explícito. Sem `tzinfo` não há como saber se o valor já era UTC, então
    assumir outra coisa seria inventar hora.
    """
    if instante.tzinfo is None:
        raise ValueError(
            f"instante sem fuso horário ({instante!r}); o manifest grava tudo em "
            f"UTC com fuso explícito, e um datetime ingênuo não diz qual é o dele"
        )
    return instante.astimezone(timezone.utc)


def _serializa_instante(instante: datetime | None) -> str | None:
    """ISO 8601 em UTC com fuso explícito, ou nulo."""
    return None if instante is None else _em_utc(instante).isoformat()


def _desserializa_instante(bruto: str | None) -> datetime | None:
    """Volta do ISO 8601 para `datetime` UTC, preservando o nulo."""
    return None if bruto is None else _em_utc(datetime.fromisoformat(bruto))


@dataclass(frozen=True)
class MinutoCapturado:
    """Um minuto que virou clipe em disco.

    Os três primeiros campos são a associação que AC-003.1 exige. O
    `relogio_local` é o quarto e vem separado de propósito: por SUP-009 ele é
    diagnóstico e nada mais, e na serialização carrega isso no próprio nome da
    chave (`relogio_local_diagnostico`), para que ninguém o confunda com a
    referência de tempo da sessão ao ler o JSON.

    O `sha256` é a identidade de **conteúdo** de SUP-051, ao lado do ETag e não
    no lugar dele: o ETag pode mudar sem que o vídeo mude, e é isso que AC-004.7
    passa a recusar. É nulo em manifest versão 1, gravado antes do campo existir.
    """

    minuto: int
    arquivo: str
    etag: str
    last_modified: datetime
    relogio_local: datetime
    sha256: str | None = None


@dataclass(frozen=True)
class MinutoPerdido:
    """Um minuto que não virou clipe, e por quê.

    O motivo é texto livre porque quem o escreve é o laço de captura (T-07), que
    conhece os caminhos de perda: ETag parado por toda a janela (AC-004.2),
    headers ausentes (D-4), download esgotado (AC-004.1) e clipe ilegível
    (AC-004.3). A lista precisa ficar registrada por AC-004.5 e AC-004.6, e
    AC-008.4 depende dela para distinguir minuto sem vídeo de minuto sem
    veículo.
    """

    minuto: int
    motivo: str


class ManifestDaSessao:
    """O `manifest.json` de uma sessão, escrito incrementalmente.

    Cada minuto resolvido — capturado ou perdido — é gravado no ato, e não no
    fim da sessão: a URL da NitTrans não tem histórico, então uma queda no
    minuto 12 não pode levar junto os 11 minutos anteriores. A gravação é
    atômica (temporário no mesmo diretório mais `os.replace`), para que uma
    queda no meio da escrita não deixe um JSON truncado no lugar do manifest
    íntegro anterior.

    O objeto é a fonte em memória durante a sessão; `ler` reconstrói um
    equivalente a partir do disco para quem chegar depois.
    """

    def __init__(
        self,
        dir_sessao: str | Path,
        *,
        id_sessao: str,
        id_camera: str,
        duracao_pedida: int,
        minutos_capturados: tuple[MinutoCapturado, ...] = (),
        minutos_perdidos: tuple[MinutoPerdido, ...] = (),
        duracao_real: int | None = None,
        encerrada_pelo_usuario: bool = False,
        manter_videos: bool = False,
        status: StatusDaSessao | None = None,
        encerrada_por_servidor_indisponivel: bool = False,
        servidor_indisponivel_desde: datetime | None = None,
    ) -> None:
        self.dir_sessao = Path(dir_sessao)
        self.id_sessao = id_sessao
        self.id_camera = id_camera
        self.duracao_pedida = duracao_pedida
        self.duracao_real = duracao_real
        self.encerrada_pelo_usuario = encerrada_pelo_usuario
        self.manter_videos = manter_videos
        self.status = status
        self.encerrada_por_servidor_indisponivel = encerrada_por_servidor_indisponivel
        self.servidor_indisponivel_desde = servidor_indisponivel_desde
        self._capturados: list[MinutoCapturado] = list(minutos_capturados)
        self._perdidos: list[MinutoPerdido] = list(minutos_perdidos)

    @classmethod
    def criar(
        cls,
        dir_sessao: str | Path,
        *,
        id_sessao: str,
        id_camera: str,
        duracao_pedida: int,
        manter_videos: bool = False,
    ) -> "ManifestDaSessao":
        """Cria o diretório da sessão e grava o cabeçalho já de saída.

        O cabeçalho vai para o disco antes do primeiro minuto porque uma sessão
        que morre no minuto 1 ainda precisa deixar rastro de que existiu — e
        porque é o diretório criado aqui que recebe os `.mp4` (SUP-012).

        `manter_videos` é a decisão de preservação de AC-003.5, desligada por
        padrão (SUP-012). Fica gravada aqui, e não só na linha de comando,
        porque quem descarta os vídeos é o encerramento da sessão, depois do
        processamento (T-09) — nessa hora o comando original já não existe.
        """
        manifest = cls(
            dir_sessao,
            id_sessao=id_sessao,
            id_camera=id_camera,
            duracao_pedida=duracao_pedida,
            manter_videos=manter_videos,
        )
        manifest.dir_sessao.mkdir(parents=True, exist_ok=True)
        manifest.gravar()
        return manifest

    @property
    def caminho(self) -> Path:
        """O `manifest.json` dentro do diretório da sessão."""
        return self.dir_sessao / NOME_DO_MANIFEST

    @property
    def minutos_capturados(self) -> tuple[MinutoCapturado, ...]:
        """Os minutos que viraram clipe, em ordem de minuto."""
        return tuple(self._capturados)

    @property
    def minutos_perdidos(self) -> tuple[MinutoPerdido, ...]:
        """Os minutos não capturados, com o motivo de cada perda."""
        return tuple(self._perdidos)

    @property
    def inicio(self) -> datetime | None:
        """Last-Modified do **primeiro clipe capturado** (AC-003.4).

        Primeiro pelo número do minuto, que é a ordem da sessão. Não é o
        relógio local do início do comando, e não é o minuto 1 pedido quando
        ele foi perdido: "efetivamente capturados" é literal. Sem nenhum clipe
        capturado não há de onde tirar o período, e o valor é nulo.
        """
        if not self._capturados:
            return None
        return min(self._capturados, key=lambda item: item.minuto).last_modified

    @property
    def fim(self) -> datetime | None:
        """Last-Modified do **último clipe capturado** (AC-003.4).

        Mesma regra do início: se o último minuto pedido foi perdido, o fim é o
        do último minuto que realmente virou vídeo em disco.
        """
        if not self._capturados:
            return None
        return max(self._capturados, key=lambda item: item.minuto).last_modified

    def _rejeita_minuto_repetido(self, minuto: int) -> None:
        """Um número de minuto tem exatamente um desfecho, e uma vez só.

        Sobrescrever em silêncio faria o manifest declarar N entradas com menos
        de N clipes distintos em disco, que é justamente o que AC-003.1 exige
        que não aconteça. Isso é erro de programação do chamador, não desfecho
        de captura — não vira minuto perdido.
        """
        ja_resolvidos = {item.minuto for item in self._capturados}
        ja_resolvidos |= {item.minuto for item in self._perdidos}
        if minuto in ja_resolvidos:
            raise ValueError(
                f"o minuto {minuto} já foi resolvido neste manifest; cada minuto "
                f"da sessão é registrado uma única vez (AC-003.1)"
            )

    def registrar_minuto(
        self,
        minuto: int,
        *,
        etag: str,
        last_modified: datetime,
        relogio_local: datetime,
        arquivo: str | None = None,
        sha256: str | None = None,
    ) -> MinutoCapturado:
        """Registra um minuto capturado e grava o manifest no ato (AC-003.1).

        `arquivo` é derivado do número do minuto quando omitido, que é o caso
        normal; o parâmetro existe só para quem já gravou o clipe com outro
        nome não precisar mentir sobre ele.
        """
        self._rejeita_minuto_repetido(minuto)
        capturado = MinutoCapturado(
            minuto=minuto,
            arquivo=arquivo or nome_do_arquivo_do_minuto(minuto),
            etag=etag,
            last_modified=_em_utc(last_modified),
            relogio_local=_em_utc(relogio_local),
            sha256=sha256,
        )
        self._capturados.append(capturado)
        self._capturados.sort(key=lambda item: item.minuto)
        self.gravar()
        return capturado

    def registrar_perda(self, minuto: int, *, motivo: str) -> MinutoPerdido:
        """Registra um minuto não capturado, com o motivo, e grava no ato.

        A sessão **não** é interrompida por isso (AC-004.2): quem chama segue
        para o minuto seguinte. O motivo fica no arquivo porque AC-004.5 e
        AC-004.6 exigem a lista registrada e AC-008.4 vai precisar dela.
        """
        self._rejeita_minuto_repetido(minuto)
        perdido = MinutoPerdido(minuto=minuto, motivo=motivo)
        self._perdidos.append(perdido)
        self._perdidos.sort(key=lambda item: item.minuto)
        self.gravar()
        return perdido

    def fechar(
        self,
        resultado: ResultadoDoStatus,
        *,
        duracao_real: int,
        encerrada_pelo_usuario: bool = False,
        encerrada_por_servidor_indisponivel: bool = False,
        servidor_indisponivel_desde: datetime | None = None,
    ) -> Path:
        """Grava o desfecho da sessão: status, duração real e encerramento.

        `resultado` vem de `capture.status.classificar`, e é o chamador quem
        escolheu o denominador: o N pedido, ou a duração real quando o usuário
        encerrou a sessão (AC-003.6 e SUP-013). O manifest só registra o que
        foi decidido — não reclassifica nada.
        """
        self.status = resultado.status
        self.duracao_real = duracao_real
        self.encerrada_pelo_usuario = encerrada_pelo_usuario
        self.encerrada_por_servidor_indisponivel = encerrada_por_servidor_indisponivel
        self.servidor_indisponivel_desde = servidor_indisponivel_desde
        return self.gravar()

    def como_dicionario(self) -> dict:
        """A forma serializável do manifest, com os timestamps em UTC.

        Todos os instantes saem em ISO 8601 com fuso explícito, coerente com
        SUP-030 de `persistencia-resultados`, que vai ler este arquivo.
        """
        return {
            "versao": VERSAO_DO_MANIFEST,
            "id_sessao": self.id_sessao,
            "id_camera": self.id_camera,
            "duracao_pedida": self.duracao_pedida,
            "duracao_real": self.duracao_real,
            "encerrada_pelo_usuario": self.encerrada_pelo_usuario,
            "manter_videos": self.manter_videos,
            "encerrada_por_servidor_indisponivel": (
                self.encerrada_por_servidor_indisponivel
            ),
            "servidor_indisponivel_desde": _serializa_instante(
                self.servidor_indisponivel_desde
            ),
            "status": None if self.status is None else self.status.value,
            "inicio": _serializa_instante(self.inicio),
            "fim": _serializa_instante(self.fim),
            "minutos_perdidos": [
                {"minuto": item.minuto, "motivo": item.motivo}
                for item in self._perdidos
            ],
            "minutos": [
                {
                    "minuto": item.minuto,
                    "arquivo": item.arquivo,
                    "etag": item.etag,
                    "last_modified": _serializa_instante(item.last_modified),
                    "relogio_local_diagnostico": _serializa_instante(
                        item.relogio_local
                    ),
                    "sha256": item.sha256,
                }
                for item in self._capturados
            ],
        }

    def gravar(self) -> Path:
        """Grava o manifest inteiro de forma atômica e devolve o caminho.

        Temporário no **mesmo diretório** — `os.replace` só é atômico dentro do
        mesmo sistema de arquivos — seguido de troca. Assim o `manifest.json`
        nunca é visto pela metade: ou é a versão anterior inteira, ou a nova
        inteira. Se a escrita do temporário falhar, ele é removido e o manifest
        antigo continua de pé.
        """
        self.dir_sessao.mkdir(parents=True, exist_ok=True)
        temporario = self.caminho.with_name(f"{NOME_DO_MANIFEST}.tmp")
        try:
            temporario.write_text(
                json.dumps(self.como_dicionario(), ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            os.replace(temporario, self.caminho)
        except OSError:
            temporario.unlink(missing_ok=True)
            raise
        return self.caminho


def ler(dir_sessao: str | Path) -> ManifestDaSessao:
    """Lê o manifest de uma sessão do disco.

    Esta função é metade da entrega de T-06: `persistencia-resultados` a usa
    para gravar no SQLite (AC-008.1), `contagem-veiculos` para saber quais
    minutos existem e quais foram perdidos (AC-007.4), e o descarte de vídeos
    (T-09) para saber o que a sessão decidiu sobre preservação.

    Aceita tanto o diretório da sessão quanto o caminho direto do
    `manifest.json`, porque os dois aparecem naturalmente em quem chama.
    """
    caminho = Path(dir_sessao)
    if caminho.is_dir():
        caminho = caminho / NOME_DO_MANIFEST

    dados = json.loads(caminho.read_text(encoding="utf-8"))
    status = dados.get("status")

    return ManifestDaSessao(
        caminho.parent,
        id_sessao=dados["id_sessao"],
        id_camera=dados["id_camera"],
        duracao_pedida=dados["duracao_pedida"],
        minutos_capturados=tuple(
            MinutoCapturado(
                minuto=entrada["minuto"],
                arquivo=entrada["arquivo"],
                etag=entrada["etag"],
                last_modified=_desserializa_instante(entrada["last_modified"]),
                relogio_local=_desserializa_instante(
                    entrada["relogio_local_diagnostico"]
                ),
                # `get`, e não `[]`: manifest versão 1 não tem o campo, e a
                # ausência significa "não registrado" (SUP-051).
                sha256=entrada.get("sha256"),
            )
            for entrada in dados["minutos"]
        ),
        minutos_perdidos=tuple(
            MinutoPerdido(minuto=entrada["minuto"], motivo=entrada["motivo"])
            for entrada in dados["minutos_perdidos"]
        ),
        duracao_real=dados["duracao_real"],
        encerrada_pelo_usuario=dados["encerrada_pelo_usuario"],
        manter_videos=dados["manter_videos"],
        status=None if status is None else StatusDaSessao(status),
        # `get`: manifest versão 1 e 2 não tem os campos (D-7).
        encerrada_por_servidor_indisponivel=dados.get(
            "encerrada_por_servidor_indisponivel", False
        ),
        servidor_indisponivel_desde=_desserializa_instante(
            dados.get("servidor_indisponivel_desde")
        ),
    )
