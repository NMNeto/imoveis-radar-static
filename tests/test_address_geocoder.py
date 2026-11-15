from imoveis_radar.address_geocoder import (
    _without_type,
    geocode_endereco,
    haversine_km,
)


def _item(
    road,
    *,
    city="Cruzeiro do Sul",
    state="Acre",
    iso="BR-AC",
    lat=-7.62,
    lng=-72.67,
    category="highway",
    place_type="residential",
    house="",
    suburb="",
    addresstype=None,
    display=None,
):
    address = {"road": road, "state": state, "ISO3166-2-lvl4": iso}
    if city:
        address["city"] = city
    if house:
        address["house_number"] = house
    if suburb:
        address["suburb"] = suburb
    item = {
        "lat": str(lat),
        "lon": str(lng),
        "category": category,
        "type": place_type,
        "display_name": display or f"{road}, {city}, {state}, Brasil",
        "address": address,
    }
    if addresstype:
        item["addresstype"] = addresstype
    return item


def test_without_type():
    assert _without_type("RUA DO PURUS") == "PURUS"
    assert _without_type("AVENIDA GONCALVES GATTO") == "GONCALVES GATTO"
    assert _without_type("RODOVIA BR101") == "BR101"
    assert _without_type("CSB 9") == "CSB 9"
    # Nome de via que é um número não perde o tipo.
    assert _without_type("RUA 21 DE DEZEMBRO") == "RUA 21 DE DEZEMBRO"


def test_geocode_valida_cidade_que_so_aparece_no_display_name():
    def searcher(query, timeout=25):
        return [
            _item(
                "Rua Humberto Sales",
                city=None,
                state="Rio de Janeiro",
                iso="BR-RJ",
                lat=-22.87,
                lng=-43.05,
                display="Rua Humberto Sales, Neves, São Gonçalo, Rio de Janeiro, Brasil",
            )
        ]

    result = geocode_endereco(
        "RJ", "São Gonçalo", "RUA HUMBERTO SALES", searcher=searcher
    )
    assert result["status"] == "ok"
    assert result["precisao"] == "rua"
    assert result["lat"] == -22.87


def test_geocode_tenta_sem_tipo_e_depois_com_tipo():
    calls = []

    def searcher(query, timeout=25):
        calls.append(query)
        if query.startswith("GONCALVES GATTO"):
            return []
        return [_item("Avenida Gonçalves Gatto", city="Belford Roxo", state="Rio de Janeiro", iso="BR-RJ")]

    result = geocode_endereco(
        "RJ", "Belford Roxo", "AVENIDA GONCALVES GATTO", searcher=searcher
    )
    assert result["status"] == "ok"
    assert calls == [
        "GONCALVES GATTO, Belford Roxo - RJ, Brasil",
        "AVENIDA GONCALVES GATTO, Belford Roxo - RJ, Brasil",
    ]


def test_geocode_rejeita_cidade_errada_e_cai_no_bairro():
    def searcher(query, timeout=25):
        if query.startswith("COHAB"):
            return [
                _item(
                    "Rua do Purus",
                    category="place",
                    place_type="suburb",
                    suburb="COHAB",
                )
            ]
        # Resultado de outra cidade: precisa ser rejeitado.
        return [_item("Rua do Purus", city="Pederneiras", state="São Paulo", iso="BR-SP")]

    result = geocode_endereco(
        "AC", "Cruzeiro do Sul", "RUA DO PURUS", bairro="COHAB", searcher=searcher
    )
    assert result["status"] == "ok"
    assert result["precisao"] == "bairro"


def test_geocode_nao_encontrado():
    def searcher(query, timeout=25):
        return []

    result = geocode_endereco(
        "AC", "Cruzeiro do Sul", "RUA INEXISTENTE", searcher=searcher
    )
    assert result["status"] == "nao_encontrado"
    assert result["lat"] is None


def test_precisao_endereco_quando_numero_bate():
    def searcher(query, timeout=25):
        return [
            _item(
                "Avenida Paulista",
                city="São Paulo",
                state="São Paulo",
                iso="BR-SP",
                category="place",
                place_type="house",
                house="1000",
            )
        ]

    result = geocode_endereco(
        "SP", "São Paulo", "AVENIDA PAULISTA", numero="1000", searcher=searcher
    )
    assert result["precisao"] == "endereco"


def test_precisao_aproximada_quando_rua_nao_confere():
    def searcher(query, timeout=25):
        return [_item("Rodovia Niterói-Manilha", city="Itaboraí", state="Rio de Janeiro", iso="BR-RJ")]

    result = geocode_endereco(
        "RJ", "Itaboraí", "RODOVIA BR101", searcher=searcher
    )
    assert result["status"] == "ok"
    assert result["precisao"] == "aproximado"


def test_rejeita_resultado_de_outra_cidade_quando_cidade_e_estado_tem_o_mesmo_nome():
    def searcher(query, timeout=25):
        # Santa Eugênia fica em Nova Iguaçu, mas "Rio de Janeiro" aparece no
        # display_name como nome do estado.
        return [
            _item(
                "Estrada de Santa Eugênia",
                city=None,
                state="Rio de Janeiro",
                iso="BR-RJ",
                lat=-22.76,
                lng=-43.45,
                display=(
                    "Estrada de Santa Eugênia, Santa Eugênia, Nova Iguaçu, "
                    "Rio de Janeiro, Região Sudeste, Brasil"
                ),
            )
        ]

    result = geocode_endereco(
        "RJ", "Rio de Janeiro", "ESTRADA DE SANTA EUGENIA", searcher=searcher
    )
    assert result["status"] == "nao_encontrado"


def test_rejeita_centroide_do_municipio():
    def searcher(query, timeout=25):
        return [
            _item(
                "Itaboraí",
                city="Itaboraí",
                state="Rio de Janeiro",
                iso="BR-RJ",
                category="boundary",
                place_type="administrative",
                addresstype="city",
                display="Itaboraí, Rio de Janeiro, Região Sudeste, Brasil",
            )
        ]

    result = geocode_endereco("RJ", "Itaboraí", "RODOVIA BR101", searcher=searcher)
    assert result["status"] == "nao_encontrado"


def test_nome_de_rua_curto_e_reconhecido():
    def searcher(query, timeout=25):
        return [_item("Rua B", city="Nova Iguaçu", state="Rio de Janeiro", iso="BR-RJ")]

    result = geocode_endereco(
        "RJ", "Nova Iguaçu", "RUA B", searcher=searcher
    )
    assert result["status"] == "ok"
    assert result["precisao"] == "rua"


def test_haversine():
    distance = haversine_km(-23.55, -46.63, -22.90, -43.20)
    assert 350 < distance < 420
