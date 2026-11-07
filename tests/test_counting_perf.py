"""Orçamento de tempo por frame analisado — T-14.

Critério coberto, de `.spec/features/contagem-veiculos/spec.md`:

- AC-005.4 — na máquina de referência e com a configuração padrão, processar
  uma sessão de 15 minutos já baixada gasta no máximo **133 ms** por frame
  analisado.

O teto era 100 ms (15 min de vídeo em 15 min) e foi renegociado pelo autor do
projeto para 133 ms (15 min em 20 min) depois da primeira medição, que deu
117,7 ms. O motivo está na spec: captura e processamento são fases sequenciais,
então o processamento nunca precisou caber no tempo da captura. A amostragem de
SUP-017 continua 1 a cada 3 — quem cedeu foi o orçamento, não a acurácia.

**Este teste só é significativo na máquina de referência declarada na spec:**
notebook de 4 núcleos, 8 GB de RAM, sem GPU. Rodá-lo em qualquer outra máquina
mede o tempo daquela máquina, não o orçamento que a spec fixou — o número
resultante não serve como prova de AC-005.4.

Material (D-3): uma sessão real de 15 minutos preservada com `--keep-clips`,
apontada pela variável de ambiente `AUTO_COUNTER_PERF_SESSION`. Variável
ausente, sessão incompleta ou modelo não exportado fazem o teste **falhar** com
a mensagem do que falta e de como produzir — nunca `pytest.skip`, porque o
`audit.py` conta teste pulado como teste que falhou (D-3).

É o único teste desta feature que carrega o `.onnx` de verdade e roda a
configuração padrão de SUP-015, SUP-016 e SUP-017: é justamente o modelo real
sob a amostragem real que AC-005.4 mede.

O denominador é o número de frames que passaram por **inferência**, e não o
total de frames do vídeo — por isso o detector real entra embrulhado por um
contador que só conta as chamadas de `detectar`, sem alterar o que elas
devolvem.

**A medição inclui a gravação do progresso por evento**, por causa da feature
`acompanhamento-ao-vivo` (nota de AC-005.4 em `contagem-veiculos`): o processamento
roda com os mesmos ganchos que `session run` liga, e um `AnotadorDoEstado` real
regrava o `sessao_atual.json` (num diretório temporário) a cada evento aceito.
O orçamento de 133 ms, o denominador e a regra de falhar em vez de pular não
mudaram.

Efeito colateral assumido: processar a sessão grava o `eventos.json` dela (D-1),
como qualquer processamento. Os vídeos não são apagados — o descarte de D-5 é do
comando de T-13, e este teste não passa por ele.
"""

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from auto_counter.cameras.registry import DIRETORIO_PADRAO, carregar_registro
from auto_counter.capture.manifest import NOME_DO_MANIFEST
from auto_counter.capture.manifest import ler as ler_manifest
from auto_counter.cli import _data_dir
from auto_counter.counting.config import ConfiguracaoDoProcessamento
from auto_counter.counting.detector import Detector, criar_sessao
from auto_counter.counting.model import caminho_do_modelo, versao_do_modelo
from auto_counter.counting.session import processar_sessao
from auto_counter.pipeline.state import AnotadorDoEstado

VARIAVEL_DA_SESSAO = "AUTO_COUNTER_PERF_SESSION"
"""De onde sai a sessão real usada na medição (D-3)."""

ORCAMENTO_EM_MS = 133.0
"""Teto de AC-005.4, derivado dos 15 min de vídeo em 20 min de processamento:
1.200 s divididos pelos ~9.000 frames analisados."""

COMO_PRODUZIR = (
    "capture uma sessão de 15 minutos preservando os clipes com "
    "'uv run auto-counter session capture <id_camera> --minutes 15 --keep-clips' "
    f"e aponte {VARIAVEL_DA_SESSAO} para o diretório dela"
)


class DetectorContado:
    """O detector real, com um contador de frames que foram à inferência.

    Embrulhar em vez de instrumentar o `Detector` mantém a medição fora do
    código de produção e conta exatamente o que AC-005.4 usa como denominador:
    uma chamada de `detectar` é um frame analisado.
    """

    def __init__(self, detector) -> None:
        self._detector = detector
        self.frames_analisados = 0

    def detectar(self, frame):
        self.frames_analisados += 1
        return self._detector.detectar(frame)


def _sessao_de_medicao() -> Path:
    """O diretório da sessão real, conferido antes de qualquer inferência."""
    valor = (os.environ.get(VARIAVEL_DA_SESSAO) or "").strip()
    if not valor:
        pytest.fail(
            f"a variável {VARIAVEL_DA_SESSAO} não está definida, e sem ela não "
            f"existe sessão real para medir AC-005.4 (D-3). Para produzir uma: "
            f"{COMO_PRODUZIR}."
        )

    dir_sessao = Path(valor)
    if not dir_sessao.is_dir():
        pytest.fail(
            f"{VARIAVEL_DA_SESSAO} aponta para {dir_sessao}, que não é um "
            f"diretório de sessão. Para produzir um: {COMO_PRODUZIR}."
        )
    if not (dir_sessao / NOME_DO_MANIFEST).is_file():
        pytest.fail(
            f"a sessão {dir_sessao} não tem {NOME_DO_MANIFEST}, então não há "
            f"como saber quais minutos e qual câmera medir. Para produzir uma "
            f"sessão completa: {COMO_PRODUZIR}."
        )
    return dir_sessao


@pytest.mark.perf
def test_AC_005_4_tempo_medio_por_frame_analisado_fica_dentro_do_orcamento(
    tmp_path,
) -> None:
    dir_sessao = _sessao_de_medicao()
    manifest = ler_manifest(dir_sessao)

    ausentes = [
        capturado.arquivo
        for capturado in manifest.minutos_capturados
        if not (dir_sessao / capturado.arquivo).is_file()
    ]
    if not manifest.minutos_capturados or ausentes:
        faltando = ", ".join(ausentes) or "todos"
        pytest.fail(
            f"a sessão {dir_sessao} está incompleta: os clipes {faltando} não "
            f"estão no disco — provavelmente ela foi processada sem "
            f"'--keep-clips' e os vídeos foram descartados (D-5). Para produzir "
            f"uma sessão utilizável: {COMO_PRODUZIR}."
        )

    caminho_do_onnx = caminho_do_modelo(_data_dir())
    if not caminho_do_onnx.is_file():
        pytest.fail(
            f"o modelo de detecção não está em {caminho_do_onnx}, e este é o "
            f"único teste que roda com o modelo real. Produza-o com: "
            f"uv run auto-counter model export"
        )

    registro = carregar_registro(DIRETORIO_PADRAO)
    camera = next((c for c in registro.cameras if c.id == manifest.id_camera), None)
    if camera is None:
        disponiveis = ", ".join(c.id for c in registro.cameras) or "nenhuma"
        pytest.fail(
            f"a câmera '{manifest.id_camera}' da sessão {dir_sessao} não está "
            f"no registro {DIRETORIO_PADRAO}, e sem a linha de contagem dela "
            f"não há o que medir. Câmeras disponíveis: {disponiveis}."
        )

    # Configuração padrão, sem nenhum ajuste: é ela que AC-005.4 mede.
    config = ConfiguracaoDoProcessamento()
    detector = DetectorContado(Detector(criar_sessao(caminho_do_onnx), config))

    # O estado de progresso é real e fica em `tmp_path`: o que se mede é o custo
    # de regravá-lo a cada evento aceito, dentro do laço do processamento.
    anotador = AnotadorDoEstado(
        tmp_path,
        pid=os.getpid(),
        id_camera=camera.id,
        nome_camera=camera.nome,
        duracao_pedida=manifest.duracao_pedida,
        iniciada_em=datetime.now(timezone.utc),
    )
    anotador.iniciar()
    anotador.processamento_iniciado(
        manifest.id_sessao, len(manifest.minutos_capturados)
    )

    comeco = time.perf_counter()
    processar_sessao(
        dir_sessao,
        camera=camera,
        detector=detector,
        config=config,
        versao_do_modelo=versao_do_modelo(caminho_do_onnx),
        ao_resolver_minuto=lambda _minuto: anotador.minuto_processado(),
        ao_aceitar_evento=lambda minuto, evento: anotador.evento_aceito(
            minuto, evento.categoria
        ),
        ao_descartar_minuto=anotador.minuto_descartado,
    )
    total_em_segundos = time.perf_counter() - comeco

    analisados = detector.frames_analisados
    assert analisados > 0, (
        f"nenhum frame da sessão {dir_sessao} chegou à inferência, então não há "
        f"média para comparar com o orçamento de AC-005.4"
    )

    media_em_ms = total_em_segundos * 1000.0 / analisados
    margem_em_ms = ORCAMENTO_EM_MS - media_em_ms

    # O relatório aparece mesmo quando passa: o número vai para o TCC.
    print(
        "\n--- AC-005.4 — orçamento de tempo por frame analisado ---\n"
        f"Sessão:            {dir_sessao}\n"
        f"Câmera:            {camera.id}\n"
        f"Minutos no disco:  {len(manifest.minutos_capturados)}\n"
        f"Amostragem:        1 frame a cada {config.amostragem}\n"
        f"Limiar:            {config.limiar_de_confianca}\n"
        f"Frames analisados: {analisados}\n"
        f"Eventos aceitos:   {sum(anotador.estado.quantidades.values())}\n"
        f"Tempo total:       {total_em_segundos:.1f} s\n"
        f"Média por frame:   {media_em_ms:.1f} ms\n"
        f"Orçamento:         {ORCAMENTO_EM_MS:.0f} ms\n"
        f"Margem:            {margem_em_ms:+.1f} ms\n"
        "Válido apenas na máquina de referência da spec "
        "(4 núcleos, 8 GB, sem GPU).\n"
    )

    assert media_em_ms <= ORCAMENTO_EM_MS, (
        f"a média de {media_em_ms:.1f} ms por frame analisado estoura o "
        f"orçamento de {ORCAMENTO_EM_MS:.0f} ms de AC-005.4 "
        f"({analisados} frames em {total_em_segundos:.1f} s). Não mexa na "
        f"amostragem de SUP-017 por conta própria: o orçamento só pode ser "
        f"renegociado contra a acurácia de AC-014.3, e isso é revisão de spec."
    )
