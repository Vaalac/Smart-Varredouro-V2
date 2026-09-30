import json
from pathlib import Path
from typing import Dict, List, Optional, Set

BASE_DIR = Path(__file__).resolve().parent
JSON_PATH = BASE_DIR / "municipios_br.json"

with JSON_PATH.open("r", encoding="utf-8") as f:
    ESTADOS: Dict[str, Dict] = json.load(f)

# Mapa das 27 capitais brasileiras
CAPITAIS_BR: Dict[str, str] = {
    "AC": "Rio Branco",
    "AL": "Maceió",
    "AM": "Manaus",
    "AP": "Macapá",
    "BA": "Salvador",
    "CE": "Fortaleza",
    "DF": "Brasília",
    "ES": "Vitória",
    "GO": "Goiânia",
    "MA": "São Luís",
    "MG": "Belo Horizonte",
    "MS": "Campo Grande",
    "MT": "Cuiabá",
    "PA": "Belém",
    "PB": "João Pessoa",
    "PE": "Recife",
    "PI": "Teresina",
    "PR": "Curitiba",
    "RJ": "Rio de Janeiro",
    "RN": "Natal",
    "RO": "Porto Velho",
    "RR": "Boa Vista",
    "RS": "Porto Alegre",
    "SC": "Florianópolis",
    "SE": "Aracaju",
    "SP": "São Paulo",
    "TO": "Palmas",
}

import unicodedata

def normalizar_str(s: str) -> str:
    s = s.strip().lower()
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

# Conjunto com todos os formatos aceitos: "Cidade, UF", "Cidade - UF", e "Cidade"
MUNICIPIOS_SET: Set[str] = set()
MUNICIPIOS_NORM_MAP: Dict[str, str] = {}
MUNICIPIOS_LISTA: List[str] = []

for uf, dados in ESTADOS.items():
    for cidade in dados["cidades"]:
        chave_padrao = f"{cidade}, {uf}"
        MUNICIPIOS_SET.add(chave_padrao)
        MUNICIPIOS_SET.add(f"{cidade} - {uf}")
        MUNICIPIOS_SET.add(cidade)
        MUNICIPIOS_LISTA.append(chave_padrao)

        # Mapeamentos normalizados
        MUNICIPIOS_NORM_MAP[normalizar_str(chave_padrao)] = chave_padrao
        MUNICIPIOS_NORM_MAP[normalizar_str(f"{cidade} - {uf}")] = chave_padrao
        MUNICIPIOS_NORM_MAP[normalizar_str(cidade)] = chave_padrao

# Para retrocompatibilidade com o scraper existente
MUNICIPIOS_SP = ESTADOS["SP"]["cidades"]
REGIOES_DISPONIVEIS = MUNICIPIOS_LISTA


def obter_estados() -> Dict[str, Dict]:
    """Retorna o dicionário completo de UFs e suas cidades."""
    return ESTADOS


def obter_cidades_uf(uf: str) -> List[str]:
    """Retorna a lista de cidades de uma UF específica."""
    uf = uf.upper().strip()
    return ESTADOS.get(uf, {}).get("cidades", [])


def obter_capitais() -> List[str]:
    """Retorna a lista formatada das 27 capitais: ['São Paulo, SP', ...]."""
    return [f"{cidade}, {uf}" for uf, cidade in sorted(CAPITAIS_BR.items())]


def validar_regiao(regiao: str) -> bool:
    """Verifica se a região informada pertence à base de municípios (insensível a acentos e maiúsculas)."""
    regiao_limpa = regiao.strip()
    if regiao_limpa in MUNICIPIOS_SET:
        return True
    return normalizar_str(regiao_limpa) in MUNICIPIOS_NORM_MAP


def canonizar_regiao(regiao: str) -> str:
    """Retorna a versão canônica formatada (com acentos e UF oficial)."""
    regiao_limpa = regiao.strip()
    norm = normalizar_str(regiao_limpa)
    return MUNICIPIOS_NORM_MAP.get(norm, regiao_limpa)


def formatar_termo_busca(regiao: str) -> str:
    """
    Formata o nome da região para a busca no Google Maps.
    Ex: 'Campinas, SP' -> 'Campinas SP'
        'Belo Horizonte - MG' -> 'Belo Horizonte MG'
        'Campinas' -> 'Campinas SP' (padrão legado)
    """
    termo = regiao.replace(",", " ").replace("-", " ").strip()
    partes = termo.split()
    # Se já tem 2 letras no final que são UF
    if len(partes) >= 2 and len(partes[-1]) == 2 and partes[-1].upper() in ESTADOS:
        return termo
    # Caso seja legado sem UF, adiciona SP
    return f"{termo} SP"
