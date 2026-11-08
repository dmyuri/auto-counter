"""Testes do registro versionado de câmeras do repositório (T-05).

Os testes de `test_registry.py` e `test_url.py` usam diretórios temporários e
fixtures. Estes aqui apontam para `config/cameras/` de verdade: são a prova de
que o arquivo versionado da câmera 000013 satisfaz AC-001.1 (é carregado como
câmera completa) e AC-001.4 (o id em string monta a URL com os zeros à
esquerda preservados).

Nenhum teste aqui toca a rede: a URL é apenas montada como texto, com a base
URL injetada por `monkeypatch`.
"""

from pathlib import Path

from auto_counter.cameras.registry import carregar_registro
from auto_counter.cameras.url import VARIAVEL_BASE_URL, url_do_clipe

RAIZ = Path(__file__).resolve().parents[1]
DIRETORIO_DO_REGISTRO = RAIZ / "config" / "cameras"
ID_DA_CAMERA_DO_MVP = "000013"


def _camera_do_mvp():
    registro = carregar_registro(DIRETORIO_DO_REGISTRO)
    assert registro.rejeicoes == [], (
        "o registro versionado não pode ter arquivo rejeitado: "
        f"{[str(rejeicao) for rejeicao in registro.rejeicoes]}"
    )
    por_id = {camera.id: camera for camera in registro.cameras}
    assert ID_DA_CAMERA_DO_MVP in por_id, (
        f"a câmera {ID_DA_CAMERA_DO_MVP} não está no registro versionado; "
        f"ids encontrados: {sorted(por_id)}"
    )
    return por_id[ID_DA_CAMERA_DO_MVP]


def test_AC_001_1_registro_versionado_carrega_n_cameras_sem_rejeicao():
    """N arquivos válidos em config/cameras/ → exatamente N câmeras."""
    arquivos = sorted(DIRETORIO_DO_REGISTRO.glob("*.yaml"))
    assert arquivos, "o registro versionado não tem nenhum arquivo de câmera"

    registro = carregar_registro(DIRETORIO_DO_REGISTRO)

    assert registro.rejeicoes == []
    assert len(registro.cameras) == len(arquivos)


def test_AC_001_1_camera_000013_tem_id_nome_sentidos_e_linha():
    """A câmera do MVP chega completa, com a linha calibrada só dela."""
    camera = _camera_do_mvp()

    assert camera.id == ID_DA_CAMERA_DO_MVP
    assert camera.nome.strip()
    assert camera.sentido_a.strip()
    assert camera.sentido_b.strip()
    assert camera.sentido_a != camera.sentido_b
    assert (camera.linha.p1.x, camera.linha.p1.y) != (
        camera.linha.p2.x,
        camera.linha.p2.y,
    )


def test_AC_001_1_linha_da_000013_esta_dentro_do_frame_de_1280x720():
    """A calibração da 000013 é declarada em pixels do frame dela (SUP-002).

    As dimensões medidas na fonte e registradas em Contexto são 1280×720. A
    validação de limites com dimensões lidas do vídeo é de T-06; aqui a
    conferência é só sobre o conteúdo do arquivo versionado.
    """
    camera = _camera_do_mvp()

    for nome, ponto in (("p1", camera.linha.p1), ("p2", camera.linha.p2)):
        assert 0 <= ponto.x <= 1279, f"{nome}.x fora de 0..1279: {ponto.x}"
        assert 0 <= ponto.y <= 719, f"{nome}.y fora de 0..719: {ponto.y}"


def test_AC_001_4_camera_000013_do_registro_monta_a_url_do_clipe(monkeypatch):
    """O id em string sobrevive ao YAML e preserva os zeros à esquerda."""
    monkeypatch.setenv(VARIAVEL_BASE_URL, "https://exemplo.invalid/videos")

    camera = _camera_do_mvp()

    assert (
        url_do_clipe(camera)
        == "https://exemplo.invalid/videos/000013/last_video.mp4"
    )


def test_AC_001_4_arquivo_da_000013_nao_declara_url():
    """A URL é derivada do id; nenhum endereço entra no arquivo versionado."""
    conteudo = (DIRETORIO_DO_REGISTRO / "000013.yaml").read_text(
        encoding="utf-8"
    )

    assert "http://" not in conteudo
    assert "https://" not in conteudo


def test_AC_020_2_camera_000013_do_registro_declara_a_previa():
    """A prévia provisória da 000013 (R-3) está declarada no registro versionado."""
    assert _camera_do_mvp().preview == "000013-v3.png"


def test_AC_031_1_registro_versionado_tem_exatamente_000012_e_000013_sem_rejeicao():
    """O registro versionado passa de 1 para 2 câmeras (SUP-101)."""
    registro = carregar_registro(DIRETORIO_DO_REGISTRO)

    assert registro.rejeicoes == [], (
        "o registro versionado não pode ter arquivo rejeitado: "
        f"{[str(rejeicao) for rejeicao in registro.rejeicoes]}"
    )
    assert len(registro.cameras) == 2
    assert sorted(camera.id for camera in registro.cameras) == [
        "000012",
        "000013",
    ]


def test_AC_031_4_url_da_000012_preserva_os_zeros_a_esquerda(monkeypatch):
    """A URL da 000012 é derivada do id, com os zeros à esquerda preservados."""
    monkeypatch.setenv(VARIAVEL_BASE_URL, "https://exemplo.invalid/videos")

    registro = carregar_registro(DIRETORIO_DO_REGISTRO)
    por_id = {camera.id: camera for camera in registro.cameras}
    assert "000012" in por_id, (
        f"a câmera 000012 não está no registro versionado; ids: {sorted(por_id)}"
    )

    assert (
        url_do_clipe(por_id["000012"])
        == "https://exemplo.invalid/videos/000012/last_video.mp4"
    )


def _camera_do_registro(id_da_camera):
    registro = carregar_registro(DIRETORIO_DO_REGISTRO)
    assert registro.rejeicoes == []
    por_id = {camera.id: camera for camera in registro.cameras}
    assert id_da_camera in por_id, (
        f"a câmera {id_da_camera} não está no registro versionado; "
        f"ids encontrados: {sorted(por_id)}"
    )
    return por_id[id_da_camera]


def test_AC_031_2_camera_000012_tem_id_nome_sentidos_distintos_e_linha_nao_degenerada():
    """A 000012 chega completa. A parte de resolução fica em T-10 (D-3)."""
    camera = _camera_do_registro("000012")

    assert isinstance(camera.id, str)
    assert camera.id == "000012"
    assert camera.nome == "Praia x Mariz Barros"
    assert camera.sentido_a.strip()
    assert camera.sentido_b.strip()
    assert camera.sentido_a != camera.sentido_b
    assert (camera.linha.p1.x, camera.linha.p1.y) != (
        camera.linha.p2.x,
        camera.linha.p2.y,
    )


def test_SUP_086_camera_000013_declara_1280x720():
    camera = _camera_do_registro("000013")

    assert (camera.resolucao.largura, camera.resolucao.altura) == (1280, 720)


def test_SUP_086_camera_000012_declara_1920x1080():
    camera = _camera_do_registro("000012")

    assert (camera.resolucao.largura, camera.resolucao.altura) == (1920, 1080)


def test_AC_031_3_camera_000013_mantem_nome_sentidos_linha_e_previa():
    """A 000013 segue idêntica a antes da feature; pega edição acidental."""
    camera = _camera_do_registro("000013")

    assert camera.nome == "Praça Getúlio Vargas"
    assert camera.sentido_a == "Icaraí"
    assert camera.sentido_b == "Centro"
    assert (camera.linha.p1.x, camera.linha.p1.y) == (1053, 348)
    assert (camera.linha.p2.x, camera.linha.p2.y) == (351, 445)
    assert camera.preview == "000013-v3.png"
