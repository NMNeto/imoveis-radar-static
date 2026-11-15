from normalizar_enderecos import NORMALIZED_COLUMNS, normalize_rows

from imoveis_radar.addresses import (
    geocode_key,
    geocode_query,
    normalize_address,
    normalize_street,
    split_address,
)


def test_exemplo_do_problema_agrupa_quadra_e_lote():
    exemplos = [
        "RUA DO PURUS, N. S/N, QUARTEIRÃO 272 LOTE 11",
        "RUA DO PURUS, N. S/N, QUARTEIRÃO 272 LOTE 12",
        "RUA DO PURUS, N. S/N, QUARTEIRÃO 272, LOTE 10",
    ]
    normalizados = {normalize_address(endereco) for endereco in exemplos}
    assert normalizados == {"RUA DO PURUS"}

    chaves = {
        geocode_key("AC", "CRUZEIRO DO SUL", normalize_address(endereco))
        for endereco in exemplos
    }
    assert chaves == {"AC|CRUZEIRO DO SUL|RUA DO PURUS"}


def test_split_address_separa_logradouro_numero_e_complemento():
    parts = split_address("RUA SERGIPE, N. 791, SETOR 03 B QD 295 LT 16")
    assert parts.logradouro == "RUA SERGIPE"
    assert parts.numero == "791"
    assert parts.complemento == "SETOR 03 B QD 295 LT 16"
    assert parts.normalizado == "RUA SERGIPE, 791"


def test_split_address_sem_virgula():
    parts = split_address("Rua das Andirobas 796W")
    assert parts.logradouro == "RUA DAS ANDIROBAS"
    assert parts.numero == "796W"

    assert split_address("MONDAI 867").logradouro == "MONDAI"
    assert split_address("MONDAI 867").numero == "867"

    # "RUA 14" é nome de via, não número de porta.
    parts = split_address("RUA 35 CASA")
    assert parts.logradouro == "RUA 35"
    assert parts.numero == ""
    assert parts.complemento == "CASA"


def test_numero_sem_informacao_nao_entra_na_chave():
    for endereco in ("RUA X, N. SN", "RUA X, N. S/N", "RUA X, N. 0", "RUA X, N. 00"):
        parts = split_address(endereco)
        assert parts.numero == ""
        assert parts.normalizado == "RUA X"


def test_numero_normalizado():
    assert split_address("RUA X, N. 045").numero == "45"
    assert split_address("RUA X, N. 8A2").numero == "8A2"
    assert split_address("RUA X, N. 540A2").numero == "540A2"
    assert split_address("RUA X, N. 22-A3").numero == "22-A3"
    assert split_address("RUA X, N. Nº 47").numero == "47"
    assert split_address("BR 101, N. 50, KM 36").numero == "50"


def test_rodovia_com_km():
    parts = split_address("RODOVIA BR101, KM 295, Torre A, Distrito 01")
    assert parts.logradouro == "RODOVIA BR101"
    assert parts.numero == "KM 295"


def test_normalize_street_padroniza_tipo_e_abreviacoes():
    assert normalize_street("R. CASTRO ALVES") == "RUA CASTRO ALVES"
    assert normalize_street("Av. Paulista") == "AVENIDA PAULISTA"
    assert normalize_street("RUA DR. JOSÉ VÂNIO") == "RUA DOUTOR JOSE VANIO"
    assert normalize_street("RUA X (ANTIGA RUA 01)") == "RUA X"
    assert normalize_street("PROLONGAMENTO DA RUA DAS FLORES") == "RUA DAS FLORES"


def test_geocode_query_legivel():
    assert (
        geocode_query("AC", "Cruzeiro do Sul", "RUA DO PURUS")
        == "RUA DO PURUS, Cruzeiro do Sul - AC, Brasil"
    )


def test_normalize_rows_gera_colunas_e_fila_deduplicada():
    columns = ["ID", "UF", "Cidade", "Bairro", "Endereço", "Latitude", "Longitude", "Precisão geográfica"]
    rows = [
        {"ID": "1", "UF": "AC", "Cidade": "CRUZEIRO DO SUL", "Bairro": "COHAB", "Endereço": "RUA DO PURUS, N. S/N, QUARTEIRÃO 272 LOTE 11", "Latitude": "-7.6", "Longitude": "-72.7", "Precisão geográfica": "cidade"},
        {"ID": "2", "UF": "AC", "Cidade": "Cruzeiro do Sul", "Bairro": "Cohab", "Endereço": "RUA DO PURUS, N. S/N, QUARTEIRÃO 272 LOTE 12", "Latitude": "-7.6", "Longitude": "-72.7", "Precisão geográfica": "cidade"},
        {"ID": "3", "UF": "AC", "Cidade": "CRUZEIRO DO SUL", "Bairro": "", "Endereço": "", "Latitude": "", "Longitude": "", "Precisão geográfica": ""},
    ]

    normalized, queue, stats = normalize_rows(rows, columns)

    assert len(normalized) == 3
    assert set(NORMALIZED_COLUMNS) <= set(normalized[0])
    assert normalized[0]["Endereço normalizado"] == "RUA DO PURUS"
    assert normalized[0]["Chave de geocodificação"] == "AC|CRUZEIRO DO SUL|RUA DO PURUS"
    assert normalized[0]["Cidade normalizada"] == normalized[1]["Cidade normalizada"]

    assert len(queue) == 1
    assert queue[0]["Imóveis"] == 2
    assert queue[0]["Endereço normalizado"] == "RUA DO PURUS"

    assert stats["enderecos_distintos_antes"] == 2
    assert stats["enderecos_distintos_depois"] == 1
    assert stats["sem_endereco"] == 1


def test_normalize_rows_sem_numero_agrupa_por_logradouro():
    columns = ["UF", "Cidade", "Bairro", "Endereço"]
    rows = [
        {"UF": "SP", "Cidade": "SAO PAULO", "Bairro": "CENTRO", "Endereço": "RUA A, N. 10"},
        {"UF": "SP", "Cidade": "SAO PAULO", "Bairro": "CENTRO", "Endereço": "RUA A, N. 20"},
    ]
    _, queue, _ = normalize_rows(rows, columns, include_number=False)
    assert len(queue) == 1
    assert queue[0]["Endereço normalizado"] == "RUA A"
