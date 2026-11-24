"""Vocabulário de categorias e configuração do processamento — T-02.

Critérios cobertos, de `.spec/features/contagem-veiculos/spec.md`:

- AC-005.1 — só carro, moto, ônibus e caminhão sobrevivem; qualquer outra
  classe do modelo não tem correspondência e é descartada antes do
  rastreamento;
- AC-005.2 — o limiar de confiança padrão é o declarado em SUP-016 e limiar
  fora do intervalo válido é recusado.

A tradução devolve `None` para classe desconhecida: quem descarta é o chamador
(T-04). As quatro categorias são fechadas — uma quinta é migration nova
(`CLAUDE.md`), não decisão de teste.
"""

import dataclasses

import pytest

from auto_counter.counting.config import (
    Categoria,
    ConfiguracaoDoProcessamento,
    categoria_da_classe_coco,
)


def test_AC_005_1_classe_coco_fora_das_quatro_categorias_nao_tem_correspondencia():
    # Pessoa (0), bicicleta (1) e semáforo (9) são exemplos citados na tarefa;
    # o restante do vocabulário COCO segue a mesma regra.
    assert categoria_da_classe_coco(0) is None
    assert categoria_da_classe_coco(1) is None
    assert categoria_da_classe_coco(9) is None
    assert categoria_da_classe_coco(4) is None
    assert categoria_da_classe_coco(6) is None
    assert categoria_da_classe_coco(79) is None


def test_AC_005_1_as_quatro_classes_de_veiculo_mapeiam_para_as_quatro_categorias():
    assert categoria_da_classe_coco(2) is Categoria.CARRO
    assert categoria_da_classe_coco(3) is Categoria.MOTO
    assert categoria_da_classe_coco(5) is Categoria.ONIBUS
    assert categoria_da_classe_coco(7) is Categoria.CAMINHAO

    # O enum é fechado: exatamente estas quatro, e nenhuma a mais.
    assert [categoria.name for categoria in Categoria] == [
        "CARRO",
        "MOTO",
        "ONIBUS",
        "CAMINHAO",
    ]


def test_AC_005_2_o_limiar_padrao_de_confianca_e_o_declarado_na_spec():
    configuracao = ConfiguracaoDoProcessamento()

    assert configuracao.limiar_de_confianca == 0.35  # SUP-016
    assert configuracao.amostragem == 3  # SUP-017
    assert configuracao.tamanho_de_entrada == 640  # SUP-015
    assert configuracao.janela_de_emenda_em_segundos == 2.0  # AC-007.1
    assert configuracao.tolerancia_da_assinatura == 0.10  # SUP-019


def test_AC_005_2_limiar_configurado_fora_do_intervalo_valido_e_recusado():
    with pytest.raises(ValueError) as acima:
        ConfiguracaoDoProcessamento(limiar_de_confianca=1.4)
    assert "limiar_de_confianca" in str(acima.value)
    assert "1.4" in str(acima.value)

    with pytest.raises(ValueError) as abaixo:
        ConfiguracaoDoProcessamento(limiar_de_confianca=-0.1)
    assert "limiar_de_confianca" in str(abaixo.value)
    assert "-0.1" in str(abaixo.value)


def test_AC_005_2_o_limiar_configurado_substitui_o_padrao():
    # SUP-016: o limiar é configurável, e o valor usado fica registrado na
    # sessão — por isso ele viaja na configuração, que T-07 grava.
    configuracao = ConfiguracaoDoProcessamento(limiar_de_confianca=0.5)

    assert configuracao.limiar_de_confianca == 0.5


def test_AC_005_2_a_configuracao_e_congelada():
    configuracao = ConfiguracaoDoProcessamento()

    with pytest.raises(dataclasses.FrozenInstanceError):
        configuracao.limiar_de_confianca = 0.9


def test_amostragem_menor_que_um_frame_e_recusada():
    # SUP-017: 1 frame a cada N, com N inteiro >= 1.
    with pytest.raises(ValueError) as zero:
        ConfiguracaoDoProcessamento(amostragem=0)
    assert "amostragem" in str(zero.value)
    assert "0" in str(zero.value)

    with pytest.raises(ValueError):
        ConfiguracaoDoProcessamento(amostragem=-3)


def test_janela_de_emenda_e_tolerancia_negativas_sao_recusadas():
    with pytest.raises(ValueError) as janela:
        ConfiguracaoDoProcessamento(janela_de_emenda_em_segundos=-1.0)
    assert "janela_de_emenda_em_segundos" in str(janela.value)

    with pytest.raises(ValueError) as tolerancia:
        ConfiguracaoDoProcessamento(tolerancia_da_assinatura=-0.01)
    assert "tolerancia_da_assinatura" in str(tolerancia.value)


def test_SUP_090_frames_por_segundo_padrao_e_10():
    # SUP-090 (processamento-upload): 10 frames analisados por segundo de vídeo.
    assert ConfiguracaoDoProcessamento().frames_por_segundo == 10


def test_SUP_090_frames_por_segundo_menor_que_1_e_recusado():
    with pytest.raises(ValueError) as zero:
        ConfiguracaoDoProcessamento(frames_por_segundo=0)
    assert "frames_por_segundo" in str(zero.value)
    assert "0" in str(zero.value)
    assert "SUP-090" in str(zero.value)

    with pytest.raises(ValueError):
        ConfiguracaoDoProcessamento(frames_por_segundo=-10)


def test_SUP_017_amostragem_da_sessao_ao_vivo_continua_3():
    # A amostragem por fps efetivo é do upload; a ao vivo segue 1 a cada 3.
    configuracao = ConfiguracaoDoProcessamento()

    assert configuracao.amostragem == 3
    assert ConfiguracaoDoProcessamento(frames_por_segundo=5).amostragem == 3
