"""Trava de sessão única — T-04.

Critérios cobertos, de `.spec/features/interface-sessao/spec.md`:

- AC-013.1 — a segunda sessão é recusada com mensagem que informa a câmera e o
  horário de início da que está em curso, e a sessão em andamento não é
  afetada;
- AC-013.2 — a trava de um processo que terminou, ou cujo PID foi reaproveitado
  por outro, é órfã e é ignorada.

"Vivo" nos testes é o próprio processo do pytest ou um filho que dorme; "morto"
é um filho que já terminou. Nada aqui toca a rede nem grava fora de `tmp_path`.
"""

import ast
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import psutil
import pytest

from auto_counter.pipeline import lock
from auto_counter.pipeline.lock import (
    NOME_DA_TRAVA,
    OutraSessaoEmAndamentoError,
    adquirir_trava,
    ler_trava,
)

INICIO = datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc)


def agora() -> datetime:
    return INICIO


def adquirir(data_dir, **extra):
    return adquirir_trava(
        data_dir,
        comando=extra.pop("comando", "run"),
        id_camera=extra.pop("id_camera", "000013"),
        nome_camera=extra.pop("nome_camera", "Av. Roberto Silveira"),
        agora=agora,
        **extra,
    )


def grava_trava(data_dir: Path, *, pid: int, criado_em: float, **campos) -> Path:
    """Escreve uma trava à mão, como outro processo a deixaria."""
    conteudo = {
        "pid": pid,
        "criado_em_do_processo": criado_em,
        "comando": "run",
        "id_camera": "000042",
        "nome_camera": "Outro local",
        "iniciada_em": INICIO.isoformat(),
    }
    conteudo.update(campos)
    data_dir.mkdir(parents=True, exist_ok=True)
    caminho = data_dir / NOME_DA_TRAVA
    caminho.write_text(json.dumps(conteudo), encoding="utf-8")
    return caminho


@pytest.fixture
def processo_vivo():
    filho = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        yield filho.pid, psutil.Process(filho.pid).create_time()
    finally:
        filho.kill()
        filho.wait()


def test_AC_013_1_segunda_aquisicao_e_recusada_com_camera_e_horario_de_inicio(
    tmp_path,
):
    with adquirir(tmp_path):
        with pytest.raises(OutraSessaoEmAndamentoError) as recusa:
            with adquirir(tmp_path, id_camera="000042", nome_camera="Outro"):
                pass

    mensagem = str(recusa.value)
    assert "Av. Roberto Silveira" in mensagem
    assert "000013" in mensagem
    assert "07/09/2026" in mensagem
    assert recusa.value.info.id_camera == "000013"


def test_AC_013_1_a_recusa_nao_altera_a_trava_da_sessao_em_curso(tmp_path):
    with adquirir(tmp_path):
        antes = (tmp_path / NOME_DA_TRAVA).read_bytes()

        with pytest.raises(OutraSessaoEmAndamentoError):
            with adquirir(tmp_path, id_camera="000042"):
                pass

        assert (tmp_path / NOME_DA_TRAVA).read_bytes() == antes


def test_AC_013_1_o_horario_da_mensagem_esta_no_horario_de_brasilia(tmp_path):
    with adquirir(tmp_path):
        with pytest.raises(OutraSessaoEmAndamentoError) as recusa:
            with adquirir(tmp_path):
                pass

    assert "08:00" in str(recusa.value)
    assert "11:00" not in str(recusa.value)


def test_AC_013_1_trava_de_outro_processo_vivo_e_recusada(tmp_path, processo_vivo):
    pid, criado_em = processo_vivo
    grava_trava(tmp_path, pid=pid, criado_em=criado_em)

    with pytest.raises(OutraSessaoEmAndamentoError) as recusa:
        with adquirir(tmp_path):
            pass

    assert recusa.value.info.pid == pid
    assert recusa.value.info.id_camera == "000042"
    assert ler_trava(tmp_path) is not None


def test_AC_013_2_trava_de_processo_morto_e_ignorada(tmp_path):
    filho = subprocess.Popen([sys.executable, "-c", "pass"])
    criado_em = psutil.Process(filho.pid).create_time()
    filho.wait()
    grava_trava(tmp_path, pid=filho.pid, criado_em=criado_em)

    with adquirir(tmp_path) as info:
        assert info.pid == psutil.Process().pid
        assert json.loads((tmp_path / NOME_DA_TRAVA).read_text("utf-8"))["pid"] == info.pid


def test_AC_013_2_trava_com_pid_reaproveitado_e_ignorada(tmp_path):
    proprio = psutil.Process()
    grava_trava(tmp_path, pid=proprio.pid, criado_em=proprio.create_time() - 3600)

    with adquirir(tmp_path):
        assert ler_trava(tmp_path) is not None


def test_AC_013_2_trava_ilegivel_e_tratada_como_orfa(tmp_path):
    (tmp_path / NOME_DA_TRAVA).write_text("{não é json", encoding="utf-8")

    with adquirir(tmp_path):
        assert ler_trava(tmp_path) is not None


def test_a_trava_e_liberada_ao_sair_mesmo_com_excecao(tmp_path):
    with pytest.raises(ValueError):
        with adquirir(tmp_path):
            raise ValueError("falha no meio da sessão")

    assert not (tmp_path / NOME_DA_TRAVA).exists()
    with adquirir(tmp_path):
        pass


def test_a_trava_de_outro_processo_nunca_e_removida_por_este(tmp_path, processo_vivo):
    pid, criado_em = processo_vivo

    with adquirir(tmp_path):
        # Outro processo assume o arquivo no meio da sessão.
        caminho = grava_trava(tmp_path, pid=pid, criado_em=criado_em)

    assert caminho.exists()
    assert json.loads(caminho.read_text("utf-8"))["pid"] == pid


def test_ler_trava_nao_apaga_a_trava_orfa(tmp_path):
    caminho = grava_trava(tmp_path, pid=2**22 + 12345, criado_em=1.0)

    assert ler_trava(tmp_path) is None
    assert caminho.exists()


def test_ler_trava_sem_arquivo_devolve_none(tmp_path):
    assert ler_trava(tmp_path) is None
    assert ler_trava(tmp_path / "nao_existe") is None


def test_adquirir_cria_o_diretorio_de_dados(tmp_path):
    destino = tmp_path / "novo" / "data"

    with adquirir(destino):
        assert (destino / NOME_DA_TRAVA).is_file()


def test_nao_sobra_arquivo_temporario(tmp_path):
    with adquirir(tmp_path):
        pass
    with pytest.raises(OutraSessaoEmAndamentoError):
        with adquirir(tmp_path):
            with adquirir(tmp_path):
                pass

    assert list(tmp_path.glob("*.tmp")) == []


def test_o_modulo_nao_usa_os_kill():
    arvore = ast.parse(Path(lock.__file__).read_text(encoding="utf-8"))
    chamadas = [
        no
        for no in ast.walk(arvore)
        if isinstance(no, ast.Attribute)
        and no.attr == "kill"
        and isinstance(no.value, ast.Name)
        and no.value.id == "os"
    ]

    assert chamadas == []
