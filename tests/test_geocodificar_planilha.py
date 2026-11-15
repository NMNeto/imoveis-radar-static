from geocodificar_planilha import (
    GEO_COLUMNS,
    apply_results,
    collect_targets,
    load_cache,
    save_cache,
)

COLUMNS = [
    "ID",
    "UF",
    "Cidade",
    "Bairro",
    "Endereço",
    "Latitude",
    "Longitude",
    "Precisão geográfica",
    "Logradouro normalizado",
    "Número normalizado",
    "Complemento",
    "Endereço normalizado",
    "Cidade normalizada",
    "Bairro normalizado",
    "Chave de geocodificação",
    "Consulta de geocodificação",
]


def _row(row_id, endereco, numero="", chave=None, logradouro=None):
    if logradouro is None:
        logradouro = "RUA DO PURUS"
    endereco_normalizado = f"{logradouro}, {numero}" if numero else logradouro
    if chave is None:
        chave = f"AC|CRUZEIRO DO SUL|{endereco_normalizado}"
    return {
        "ID": row_id,
        "UF": "AC",
        "Cidade": "CRUZEIRO DO SUL",
        "Bairro": "COHAB",
        "Endereço": endereco,
        "Latitude": "-7.63",
        "Longitude": "-72.67",
        "Precisão geográfica": "cidade",
        "Logradouro normalizado": logradouro,
        "Número normalizado": numero,
        "Complemento": "",
        "Endereço normalizado": endereco_normalizado,
        "Cidade normalizada": "CRUZEIRO DO SUL",
        "Bairro normalizado": "COHAB",
        "Chave de geocodificação": chave,
        "Consulta de geocodificação": "",
    }


def test_collect_targets_agrupa_por_logradouro_por_padrao():
    rows = [
        _row("1", "RUA DO PURUS, N. 10, BL 1", "10", "AC|CRUZEIRO DO SUL|RUA DO PURUS, 10"),
        _row("2", "RUA DO PURUS, N. 20, BL 2", "20", "AC|CRUZEIRO DO SUL|RUA DO PURUS, 20"),
    ]
    targets = collect_targets(rows, COLUMNS)
    assert len(targets) == 1
    assert targets[0]["key"] == "AC|CRUZEIRO DO SUL|RUA DO PURUS"
    assert targets[0]["logradouro"] == "RUA DO PURUS"
    assert targets[0]["numero"] == ""
    assert targets[0]["imoveis"] == 2


def test_collect_targets_por_numero():
    rows = [
        _row("1", "RUA DO PURUS, N. 10", "10", "AC|CRUZEIRO DO SUL|RUA DO PURUS, 10"),
        _row("2", "RUA DO PURUS, N. 20", "20", "AC|CRUZEIRO DO SUL|RUA DO PURUS, 20"),
    ]
    targets = collect_targets(rows, COLUMNS, por_numero=True)
    assert len(targets) == 2
    assert {target["numero"] for target in targets} == {"10", "20"}


def test_apply_results_mapeia_resultado_da_rua_para_todos_os_numeros():
    rows = [
        _row("1", "RUA DO PURUS, N. 10", "10", "AC|CRUZEIRO DO SUL|RUA DO PURUS, 10"),
        _row("2", "RUA DO PURUS, N. 20", "20", "AC|CRUZEIRO DO SUL|RUA DO PURUS, 20"),
        _row(
            "3",
            "RUA OUTRA",
            "",
            "AC|CRUZEIRO DO SUL|RUA OUTRA",
            logradouro="RUA OUTRA",
        ),
    ]
    queries = {
        "AC|CRUZEIRO DO SUL|RUA DO PURUS": {
            "status": "ok",
            "lat": -7.62,
            "lng": -72.67,
            "precisao": "rua",
            "fonte": "nominatim",
            "endereco_retornado": "Rua do Purus, Cruzeiro do Sul, Acre, Brasil",
        }
    }
    output = apply_results(rows, COLUMNS, queries)
    assert set(GEO_COLUMNS) <= set(output[0])
    assert output[0]["Status geocodificação"] == "ok"
    assert output[0]["Precisão geocodificada"] == "rua"
    assert output[0]["Latitude geocodificada"] == "-7.620000"
    assert output[0]["Distância da sede (km)"]
    assert output[1]["Status geocodificação"] == "ok"
    assert output[2]["Status geocodificação"] == "pendente"


def test_apply_results_sem_endereco():
    rows = [_row("1", "", "", "")]
    output = apply_results(rows, COLUMNS, {})
    assert output[0]["Status geocodificação"] == "sem_endereco"


def test_cache_ida_e_volta(tmp_path):
    path = tmp_path / "cache.json"
    cache = load_cache(path)
    assert cache["queries"] == {}
    cache["queries"]["AC|CRUZEIRO DO SUL|RUA DO PURUS"] = {"status": "ok"}
    save_cache(path, cache)
    loaded = load_cache(path)
    assert loaded["queries"]["AC|CRUZEIRO DO SUL|RUA DO PURUS"]["status"] == "ok"
    assert loaded["updated"]
