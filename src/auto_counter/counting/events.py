"""O evento de cruzamento e o `eventos.json` da sessão — T-07.

Comportamento em `.spec/features/contagem-veiculos/spec.md`:

- AC-006.1 — na parte de **durabilidade**: o evento registrado carrega
  timestamp, categoria, sentido e id de rastreio. Quem decide *quando* um
  cruzamento vira evento é T-09; este módulo só sabe guardá-lo e trazê-lo de
  volta inteiro.

Alimenta AC-008.1 e AC-008.2 de `persistencia-resultados`: a configuração
efetivamente usada — limiar (SUP-016), amostragem (SUP-017) e versão do modelo
(SUP-027) — fica gravada junto dos eventos, e as duas listas de minutos
sustentam a distinção de AC-008.4 entre minuto sem veículo (processado, zero
eventos) e minuto sem vídeo (não processado, com motivo — D-4).

Implementa D-1: o arquivo é `eventos.json`, no diretório da sessão, ao lado do
`manifest.json`, porque `persistencia-resultados` ainda não existe e sem ele
AC-006.1 ficaria sem prova durável.

Os campos além dos quatro de AC-006.1 existem por necessidade de tarefas
vizinhas, e cada um está justificado no seu lugar em `Evento`.

Timestamps em ISO 8601 UTC com fuso explícito (SUP-030). A escrita é atômica,
no mesmo padrão de `capture/manifest.py` — reproduzido aqui, e não importado
de lá, porque aquele módulo não expõe a rotina.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from auto_counter.counting.config import Categoria, ConfiguracaoDoProcessamento

NOME_DO_ARQUIVO_DE_EVENTOS = "eventos.json"
"""Nome do arquivo dentro do diretório da sessão (D-1)."""

VERSAO_DOS_EVENTOS = 1
"""Versão do formato gravado.

Mesmo motivo do `manifest.json`: sem um número de versão, uma mudança futura de
formato seria indistinguível de um arquivo corrompido para quem lê depois —
`persistencia-resultados` e `validacao-acuracia`.
"""


def id_de_rastreio_composto(minuto: int, id_do_rastreador: int) -> str:
    """O id de rastreio do evento: `<minuto>:<id do ByteTrack>` (D-9).

    O ByteTrack reinicia a numeração a cada clipe, então o id 7 do minuto 3 e o
    id 7 do minuto 4 seriam o mesmo id — exatamente o reaproveitamento que
    AC-007.3 proíbe. Prefixar pelo minuto torna o id único na sessão sem
    inventar continuidade de identidade entre clipes, que está em Fora de
    escopo.
    """
    return f"{minuto}:{id_do_rastreador}"


def _em_utc(instante: datetime) -> datetime:
    """Normaliza para UTC ciente de fuso, como exige a serialização (SUP-030).

    Sem `tzinfo` não há como saber se o valor já era UTC, e assumir seria
    inventar hora. Mesma recusa de `capture/manifest.py` e de
    `counting/timestamps.py`.
    """
    if instante.tzinfo is None:
        raise ValueError(
            f"instante sem fuso horário ({instante!r}); o evento é datado em UTC "
            f"com fuso explícito, e um datetime ingênuo não diz qual é o dele"
        )
    return instante.astimezone(timezone.utc)


@dataclass(frozen=True)
class Evento:
    """Um cruzamento da linha de contagem, já decidido.

    Os quatro primeiros campos são os que AC-006.1 exige. Os demais existem por
    necessidade explícita de outras entregas:

    - `confianca` é exigida por AC-008.2. Nenhuma spec a define, e a definição é
      fixada em T-07: **média das confianças das detecções da categoria
      vencedora ao longo do rastreio** (SUP-023). É determinística, que é o que
      AC-014.5 exige — não é a confiança do frame do cruzamento, que variaria
      com o instante em que o veículo tocou a linha;
    - `minuto` e `indice_do_frame` são o diagnóstico do cruzamento, e é deles
      que T-10 tira se o evento caiu na janela de emenda de AC-007.1;
    - `posicao_na_linha` é a fração de 0 a 1 ao longo da linha, terceiro
      componente da assinatura de SUP-019.

    Congelada porque um evento gravado é fato consumado: reescrever a categoria
    ou o sentido depois da decisão de T-09 quebraria a correspondência entre o
    que foi contado e o que está no disco.
    """

    timestamp: datetime
    categoria: Categoria
    sentido: str
    id_de_rastreio: str
    confianca: float
    minuto: int
    indice_do_frame: int
    posicao_na_linha: float

    def __post_init__(self) -> None:
        """Recusa o que não poderia ser gravado nem relido sem ambiguidade."""
        object.__setattr__(self, "timestamp", _em_utc(self.timestamp))

        if not 0.0 <= self.confianca <= 1.0:
            raise ValueError(
                f"confianca precisa estar entre 0 e 1, e não {self.confianca}; "
                f"é a média das confianças da categoria vencedora (SUP-023)"
            )

        if not 0.0 <= self.posicao_na_linha <= 1.0:
            raise ValueError(
                f"posicao_na_linha é uma fração de 0 a 1 ao longo da linha, e "
                f"não {self.posicao_na_linha} (SUP-019)"
            )

    def como_dicionario(self) -> dict:
        """A forma serializável do evento, com o timestamp em ISO 8601 UTC."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "categoria": self.categoria.value,
            "sentido": self.sentido,
            "id_de_rastreio": self.id_de_rastreio,
            "confianca": self.confianca,
            "minuto": self.minuto,
            "indice_do_frame": self.indice_do_frame,
            "posicao_na_linha": self.posicao_na_linha,
        }

    @classmethod
    def do_dicionario(cls, dados: dict) -> "Evento":
        """Reconstrói o evento a partir do que foi gravado."""
        return cls(
            timestamp=_em_utc(datetime.fromisoformat(dados["timestamp"])),
            categoria=Categoria(dados["categoria"]),
            sentido=dados["sentido"],
            id_de_rastreio=dados["id_de_rastreio"],
            confianca=dados["confianca"],
            minuto=dados["minuto"],
            indice_do_frame=dados["indice_do_frame"],
            posicao_na_linha=dados["posicao_na_linha"],
        )


@dataclass(frozen=True)
class MinutoNaoProcessado:
    """Um minuto que não chegou a ser analisado, e por quê.

    O motivo é texto livre porque quem o escreve é o laço de processamento
    (T-12), que conhece os caminhos de D-4: clipe ausente, clipe ilegível, e o
    minuto que já vinha perdido da captura (AC-004.5). O par sustenta AC-008.4:
    minuto sem vídeo não é minuto sem veículo.
    """

    minuto: int
    motivo: str


@dataclass(frozen=True)
class RegistroDeEventos:
    """O conteúdo inteiro do `eventos.json` de uma sessão.

    Congelado pelo mesmo motivo de `ConfiguracaoDoProcessamento`: o que é
    gravado tem de ser o que foi usado. Cada minuto concluído remonta o registro
    e grava — o laço da sessão (T-12) escreve incrementalmente, pelo mesmo
    motivo do `manifest.json`: uma queda no minuto 14 não pode levar junto os 13
    minutos já analisados. Reprocessar nem sempre é possível, porque o descarte
    dos vídeos (D-5) acontece ao fim do processamento e, sem `--keep-clips`,
    aquela sessão não tem mais o que reprocessar.
    """

    id_sessao: str
    id_camera: str
    configuracao: ConfiguracaoDoProcessamento
    versao_do_modelo: str
    minutos_processados: tuple[int, ...] = ()
    minutos_nao_processados: tuple[MinutoNaoProcessado, ...] = ()
    eventos: tuple[Evento, ...] = ()

    @property
    def eventos_em_ordem(self) -> tuple[Evento, ...]:
        """Os eventos ordenados por timestamp, que é como D-1 pede a lista.

        O desempate é pelo índice do frame e depois pelo id de rastreio: dentro
        de um mesmo segundo — a resolução de AC-006.5 — vários cruzamentos
        empatam no timestamp, e sem desempate a ordem gravada dependeria da
        ordem de inserção, o que tiraria a reprodutibilidade de AC-014.5.
        """
        return tuple(
            sorted(
                self.eventos,
                key=lambda item: (
                    item.timestamp,
                    item.indice_do_frame,
                    item.id_de_rastreio,
                ),
            )
        )

    def como_dicionario(self) -> dict:
        """A forma serializável do registro inteiro.

        A configuração entra achatada, com a versão do modelo ao lado dos
        parâmetros, porque é assim que AC-008.1 a consome: "a configuração
        usada" é um bloco só, e não um objeto mais um campo solto.
        """
        return {
            "versao": VERSAO_DOS_EVENTOS,
            "id_sessao": self.id_sessao,
            "id_camera": self.id_camera,
            "configuracao": {
                "limiar_de_confianca": self.configuracao.limiar_de_confianca,
                "amostragem": self.configuracao.amostragem,
                "tamanho_de_entrada": self.configuracao.tamanho_de_entrada,
                "janela_de_emenda_em_segundos": (
                    self.configuracao.janela_de_emenda_em_segundos
                ),
                "tolerancia_da_assinatura": self.configuracao.tolerancia_da_assinatura,
                "versao_do_modelo": self.versao_do_modelo,
            },
            "minutos_processados": list(self.minutos_processados),
            "minutos_nao_processados": [
                {"minuto": item.minuto, "motivo": item.motivo}
                for item in self.minutos_nao_processados
            ],
            "eventos": [item.como_dicionario() for item in self.eventos_em_ordem],
        }

    def gravar(self, dir_sessao: str | Path) -> Path:
        """Grava o `eventos.json` de forma atômica e devolve o caminho.

        Temporário no **mesmo diretório** — `os.replace` só é atômico dentro do
        mesmo sistema de arquivos — seguido de troca, igual a
        `capture/manifest.py`. Assim o arquivo nunca é visto pela metade: ou é a
        versão anterior inteira, ou a nova inteira. Se a escrita do temporário
        falhar, ele é removido e o arquivo anterior continua de pé.
        """
        dir_sessao = Path(dir_sessao)
        dir_sessao.mkdir(parents=True, exist_ok=True)
        caminho = dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS
        temporario = caminho.with_name(f"{NOME_DO_ARQUIVO_DE_EVENTOS}.tmp")
        try:
            temporario.write_text(
                json.dumps(self.como_dicionario(), ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            os.replace(temporario, caminho)
        except OSError:
            temporario.unlink(missing_ok=True)
            raise
        return caminho


def ler(dir_sessao: str | Path) -> RegistroDeEventos:
    """Lê o `eventos.json` de uma sessão do disco.

    Metade da entrega de T-07: `persistencia-resultados` a usa para gravar no
    banco (AC-008.1 e AC-008.2), `validacao-acuracia` para parear com o ground
    truth (AC-014.2), e T-12 para não reprocessar o que já está gravado.

    Aceita tanto o diretório da sessão quanto o caminho direto do arquivo,
    porque os dois aparecem naturalmente em quem chama — mesma cortesia de
    `capture.manifest.ler`.
    """
    caminho = Path(dir_sessao)
    if caminho.is_dir():
        caminho = caminho / NOME_DO_ARQUIVO_DE_EVENTOS

    dados = json.loads(caminho.read_text(encoding="utf-8"))
    configuracao = dados["configuracao"]

    return RegistroDeEventos(
        id_sessao=dados["id_sessao"],
        id_camera=dados["id_camera"],
        configuracao=ConfiguracaoDoProcessamento(
            limiar_de_confianca=configuracao["limiar_de_confianca"],
            amostragem=configuracao["amostragem"],
            tamanho_de_entrada=configuracao["tamanho_de_entrada"],
            janela_de_emenda_em_segundos=configuracao["janela_de_emenda_em_segundos"],
            tolerancia_da_assinatura=configuracao["tolerancia_da_assinatura"],
        ),
        versao_do_modelo=configuracao["versao_do_modelo"],
        minutos_processados=tuple(dados["minutos_processados"]),
        minutos_nao_processados=tuple(
            MinutoNaoProcessado(minuto=entrada["minuto"], motivo=entrada["motivo"])
            for entrada in dados["minutos_nao_processados"]
        ),
        eventos=tuple(Evento.do_dicionario(entrada) for entrada in dados["eventos"]),
    )
