"""Validação de acurácia contra o ground truth real — gate da entrega.

Critérios cobertos, de `.spec/features/validacao-acuracia/spec.md`:

- AC-014.3 — nos 3 clipes de referência (pico, fora de pico e noturno), o erro
  de contagem é de no máximo 10% em cada sentido e o acerto de categoria é de no
  mínimo 80%, em cada clipe;
- AC-014.4 — quando algum limite é violado, a mensagem do teste aponta clipe,
  métrica e valor medido;
- AC-014.5 — duas execuções completas sobre os mesmos clipes dão o mesmo
  veredito, sem nenhuma requisição de rede.

**Este é o único teste da suíte com o ID AC-014.3** (D-9): um teste sintético com
esse ID passaria na suíte rápida e daria a meta como atingida sem medição
nenhuma. Quem declara que a contagem "conta bem" é o resultado deste teste, e o
relatório que ele grava em `<data_dir>/validacao/`.

Material (SUP-044): `tests/ground_truth/manifest.yaml`, os CSVs de contagem
manual e os vídeos em `tests/ground_truth/clipes/`. Os dois primeiros são
versionados; os vídeos não, e estão descritos no README §Ground truth.

- manifest ou CSV ausente ou inválido: **falha**, apontando o arquivo. São
  versionados, então a ausência é repositório quebrado;
- vídeo obrigatório ausente: **pula**, nomeando os clipes. É SUP-044 literal, e
  o `audit.py` trata teste pulado igual a teste que falhou, então o gate reprova
  em vez de passar em silêncio;
- vídeo ilegível: **falha**, com clipe e motivo;
- `.onnx` ausente: **falha**, citando `uv run auto-counter model export`.

Roda o modelo real com a configuração padrão, sem nenhum ajuste (D-5), e leva
cerca de 3,5 min por execução na máquina de referência, por isso fica fora da
suíte rápida (marcador `accuracy`, SUP-047).

Se reprovar, não mexa em nada para fazer passar: nem nos limites, nem na janela
de pareamento, nem na configuração, nem nos CSVs. Leve o relatório ao autor.
Quem cede é a configuração de `contagem-veiculos`, por revisão de spec (SUP-017).
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from auto_counter.cameras.registry import DIRETORIO_PADRAO, carregar_registro
from auto_counter.cli import _data_dir
from auto_counter.counting.config import ConfiguracaoDoProcessamento
from auto_counter.counting.detector import Detector, criar_sessao
from auto_counter.counting.model import caminho_do_modelo, versao_do_modelo
from auto_counter.validation.automatic import ClipeDeReferenciaIlegivelError
from auto_counter.validation.ground_truth import (
    RAIZ_PADRAO,
    ConjuntoDeReferenciaInvalidoError,
    carregar_conjunto,
    videos_ausentes,
)
from auto_counter.validation.run import executar_validacao
from auto_counter.validation.verdict import mensagem_de_falha
from tests.conftest import rede_bloqueada

pytestmark = pytest.mark.accuracy


def _preparar():
    """Confere o material, na ordem e com o tratamento de D-10, antes de rodar."""
    try:
        conjunto = carregar_conjunto(RAIZ_PADRAO)
    except ConjuntoDeReferenciaInvalidoError as erro:
        pytest.fail(
            f"o conjunto de referência é inválido: {erro}. O formato está em "
            f"README.md, seção 'Ground truth'."
        )

    ausentes = videos_ausentes(conjunto)
    if ausentes:
        nomes = ", ".join(f"{c.condicao.value} ({c.caminho_video})" for c in ausentes)
        pytest.skip(
            f"vídeos de referência ausentes nesta máquina: {nomes}. A validação "
            f"não foi medida, e o audit.py trata teste pulado igual a teste que "
            f"falhou: o gate reprova em vez de passar em silêncio (SUP-044)."
        )

    caminho_do_onnx = caminho_do_modelo(_data_dir())
    if not caminho_do_onnx.is_file():
        pytest.fail(
            f"o modelo de detecção não está em {caminho_do_onnx}, e a validação "
            f"roda com o modelo real. Produza-o com: uv run auto-counter model export"
        )
    return conjunto, carregar_registro(DIRETORIO_PADRAO), caminho_do_onnx


def _executar(preparo, tmp_path_factory, rotulo: str, executado_em: datetime):
    """Uma execução completa: modelo novo, diretório de trabalho novo, sem rede."""
    conjunto, registro, caminho_do_onnx = preparo
    config = ConfiguracaoDoProcessamento()  # padrão, sem argumentos (D-5)
    detector = Detector(criar_sessao(caminho_do_onnx), config)
    dir_trabalho = tmp_path_factory.mktemp(f"validacao-{rotulo}")

    try:
        with rede_bloqueada() as tentativas:
            resultado, caminho_do_relatorio = executar_validacao(
                conjunto.raiz,
                registro=registro,
                detector=detector,
                config=config,
                versao_do_modelo=versao_do_modelo(caminho_do_onnx),
                dir_trabalho=dir_trabalho,
                data_dir_do_relatorio=_data_dir(),
                executado_em=executado_em,
            )
    except ClipeDeReferenciaIlegivelError as erro:
        pytest.fail(
            f"clipe de referência ilegível ({erro.condicao.value}): {erro.motivo}"
        )
    assert tentativas == [], f"a validação tentou usar a rede: {tentativas}"
    return resultado, caminho_do_relatorio


@pytest.fixture(scope="session")
def preparo():
    return _preparar()


@pytest.fixture(scope="session")
def primeira_execucao(preparo, tmp_path_factory):
    executado_em = datetime.now(timezone.utc)
    resultado, caminho = _executar(preparo, tmp_path_factory, "1", executado_em)
    return resultado, caminho, executado_em


def test_AC_014_3_os_tres_clipes_de_referencia_atendem_a_meta(primeira_execucao):
    resultado, caminho_do_relatorio, _ = primeira_execucao

    # O relatório aparece nos dois casos: o número vai para o TCC.
    print(f"\nRelatório da validação: {caminho_do_relatorio}")
    print(f"Veredito do conjunto: {'APROVADO' if resultado.veredito.passou else 'REPROVADO'}")

    assert resultado.veredito.passou, mensagem_de_falha(resultado.veredito)


def test_AC_014_5_duas_execucoes_sobre_os_clipes_reais_dao_o_mesmo_veredito(
    preparo, primeira_execucao, tmp_path_factory
):
    primeiro, caminho_um, executado_em_um = primeira_execucao
    # a segunda execução precisa de outro instante para não colidir com o
    # relatório da primeira (nome com resolução de 1 s, modo "x")
    executado_em_dois = max(
        datetime.now(timezone.utc), executado_em_um + timedelta(seconds=1)
    )

    segundo, caminho_dois = _executar(preparo, tmp_path_factory, "2", executado_em_dois)

    print(f"\nRelatórios: {caminho_um} e {caminho_dois}")

    def violacoes(resultado):
        return {
            (v.condicao, v.metrica, v.sentido) for v in resultado.veredito.violacoes
        }

    assert segundo.veredito.passou == primeiro.veredito.passou
    assert violacoes(segundo) == violacoes(primeiro)

    # Métricas diferentes com o veredito igual é alerta, não reprovação: a spec
    # exige o mesmo veredito, e exigir métricas idênticas seria um critério
    # mais duro que o dela.
    if [c.medicao for c in segundo.clipes] != [c.medicao for c in primeiro.clipes]:
        print(
            "ALERTA DE REPRODUTIBILIDADE: o veredito é o mesmo, mas as métricas "
            "das duas execuções diferem. Compare os dois relatórios."
        )
