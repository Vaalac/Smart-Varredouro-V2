import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

import duckdb

BASE_DIR = Path(__file__).resolve().parent
MUNICIPIOS_RECEITA_PATH = BASE_DIR / "municipios_receita.json"

PARQUET_BASE_URL = "https://huggingface.co/datasets/cnpjaberto/cnpj-dados-receita-brasil-2026-09/resolve/main/estabelecimentos"
TOTAL_CHUNKS = 10

NICHOS: Dict[str, Dict] = {
    "imoveis": {
        "nome": "Todas as Imobiliárias & Corretores (Oficial CRECI)",
        "cnaes": ["6821801", "6821802"],
        "descricao": "Corretagem na compra, venda, avaliação e locação de imóveis (CNAE 6821-8)",
    },
    "venda_avaliacao": {
        "nome": "Corretagem, Venda & Avaliação de Imóveis",
        "cnaes": ["6821801"],
        "descricao": "Corretores e imobiliárias focadas em compra, venda e avaliação (CNAE 6821-8/01)",
    },
    "locacao_admin": {
        "nome": "Locação & Administração Imobiliária",
        "cnaes": ["6821802"],
        "descricao": "Imobiliárias focadas em locação e aluguel (CNAE 6821-8/02)",
    },
    "loteamento_incorp": {
        "nome": "Loteadoras & Incorporadoras Imobiliárias",
        "cnaes": ["4110700", "6810201"],
        "descricao": "Incorporação de empreendimentos e loteamentos",
    },
    "custom": {
        "nome": "CNAE Imobiliário Personalizado",
        "cnaes": [],
        "descricao": "Insira códigos CNAE manuais",
    },
}

# Palavras que indicam explicitamente atividade imobiliária / corretagem
TERMOS_SALVADORES_CNPJ = [
    r'\bim[oó]ve(is|l)\b',
    r'\bimobili[aá]ri[oa]s?\b',  # imobiliaria, imobiliarias, imobiliario, imobiliarios
    r'\bcorret(or|ora|agem|ores|oras)\b',
    r'\bcreci\b',
    r'\bloteament[os]?\b',
    r'\bloteador[as]?\b',
    r'\bincorpor(adora|ação|acao|adoras|acoes|ações)\b',
    r'\bhomes?\b',
    r'\bproperties\b',
    r'\breal\s*estate\b',
    r'\bbroker[s]?\b',
    r'\burbanizad(ora|or|oras|ores)\b',
    r'\burbanismo\b',
    r'\bcondom[ií]ni[os]?\b',
    r'\bresidenc(ial|iais)\b',
    r'\blancament[os]?\b',
    r'\blançament[os]?\b',
    r'\bterrenos?\b',
    r'\bchacaras?\b',
    r'\bchácaras?\b',
    r'\bsitios?\b',
    r'\bsítios?\b',
    r'\bfazendas?\b',
]

# Termos no NOME DA EMPRESA que indicam comércios/serviços que NÃO são imobiliárias
TERMOS_BLOQUEADOS_CNPJ_NOME = [
    # Alimentos / Bebidas / Refeições / Conveniência
    r'\bmarmit[as]?\b', r'\bmarmitaria\b', r'\brefei(cao|ção|coes|ções)\b',
    r'\bsorvete[s]?\b', r'\bsorveteria\b', r'\ba[cç]a[ií]\b',
    r'\blanche[s]?\b', r'\bpizzas?\b', r'\bpizzarias?\b', r'\bhamburguer(ia)?\b',
    r'\bchoperia\b', r'\bchurrascaria\b', r'\bcervejaria\b', r'\bpastelaria\b',
    r'\bpadaria[s]?\b', r'\bconfeitaria\b', r'\bcomida[s]?\b', r'\balimento[s]?\b',
    r'\brestaurante[s]?\b', r'\bespetinho[s]?\b', r'\bsupermercado[s]?\b',
    r'\ba[cç]ougue[s]?\b', r'\bpanif[ií]cio[s]?\b', r'\bmercearia[s]?\b',
    r'\bbar\b', r'\bbare[s]?\b', r'\bpub[s]?\b', r'\bboate[s]?\b',
    r'\bconveni[eê]ncia[s]?\b', r'\btabacaria[s]?\b', r'\bpeixaria\b',
    r'\bhortifruti\b', r'\bsacol[aã]o\b',

    # Distribuição, Atacado & Comércio Geral
    r'\bdistribuidora\b', r'\batacado\b', r'\batacadista\b',
    r'\blot[eé]rica\b', r'\blavanderia\b',

    # Veículos / Motos / Mecânica / Transportes / Estacionamentos
    r'\bmotos?\b', r'\bmotocicletas?\b', r'\bve[ií]cul(o|os|a|as)?\b',
    r'\bautom[oó]ve(is|l)\b', r'\bcarros?\b', r'\bauto\s*center\b',
    r'\bautocenter\b', r'\boficina\b', r'\bmec[aâ]nica\b', r'\bauto\s*pe[cç]as\b',
    r'\bpneus?\b', r'\blava\s*jato\b', r'\blava\s*r[aá]pido\b',
    r'\bposto\b', r'\bcombust[ií]ve(is|l)\b',
    r'\bautoescola\b', r'\bauto\s*escola\b',
    r'\btransportadora[s]?\b', r'\btransporte[s]?\b', r'\bguincho\b',
    r'\bestacionamento[s]?\b',

    # Móveis residenciais / Marcenaria (sem 'i' inicial)
    r'\bmoveis\b', r'\bmóveis\b', r'\bmarcenaria\b', r'\bestofados?\b',
    r'\bcolch[aã]o\b', r'\bcolch[oõ]es\b',

    # Saúde / Beleza / Fitness / Pets
    r'\best[eé]tica\b', r'\bsal[aã]o\b', r'\bbarbearia\b', r'\bcabeleireir[oa]s?\b',
    r'\bacadamia\b', r'\bfitness\b', r'\bcrossfit\b', r'\bdentista\b',
    r'\bodontolog(ia|ico|ica)\b', r'\bcl[ií]nica\b', r'\bhospital\b',
    r'\bfarm[aá]cia\b', r'\bdrogaria\b', r'\blaborat[oó]rio\b',
    r'\bpet\s*shop\b', r'\bveterin[aá]ri[ao]\b',

    # Educação & Entretenimento
    r'\bescola\b', r'\bcol[eé]gio\b', r'\bfaculdade\b', r'\bcreche\b',
    r'\bcinema\b', r'\bteatro\b',

    # Gráfica / Informática / Comércio Especializado
    r'\bgr[aá]fica\b', r'\bxerox\b', r'\bpapelaria\b', r'\blivraria\b',
    r'\binform[aá]tica\b', r'\bcelular(es)?\b', r'\beletr[oô]nico[s]?\b',
    r'\b[oó]tica[s]?\b', r'\brelojoaria\b', r'\bjoalheria\b',
    r'\broupas?\b', r'\bcal[cç]ados?\b', r'\btecidos?\b',
    r'\bconfec(cao|ção|coes|ções)\b',

    # Hotelaria / Eventos
    r'\bhotel\b', r'\bpousada\b', r'\bmotel\b', r'\bbuffet\b',

    # Indústria & Materiais Pesados
    r'\bmetais\b', r'\bmetal[uú]rgica\b', r'\bsucatas?\b',
    r'\bvidra[cç]aria[s]?\b', r'\bserralheria[s]?\b', r'\btornearia[s]?\b'
]

# Termos no E-MAIL que revelam negócios intrusos
# Note que NUNCA bloqueamos contabilidade, escritório ou advocacia aqui!
TERMOS_BLOQUEADOS_CNPJ_EMAIL = [
    r'marmita', r'sorvete', r'eskimo', r'pizzaria', r'lanche', r'burger', r'pastel',
    r'restaurante', r'choperia', r'churrascaria', r'padaria', r'panificio',
    r'acougue', r'mercearia', r'distribuidora', r'atacado', r'conveniencia', r'tabacaria',
    r'motos', r'veiculos', r'automoveis', r'autopecas', r'autocenter', r'oficina', r'mecanica',
    r'lavajato', r'posto', r'postos', r'autoposto', r'combustivel', r'transportadora', r'estacionamento',
    r'marcenaria', r'estofados', r'colchoes', r'colchao',
    r'estetica', r'barbearia', r'salao', r'fitness', r'crossfit', r'odontologia',
    r'petshop', r'veterinaria', r'farmacia', r'drogaria', r'laboratorio',
    r'grafica', r'papelaria', r'informatica', r'roupas', r'calcados', r'confeccoes',
    r'vidracaria', r'serralheria', r'metalurgica'
]


def email_eh_intruso_cnpj(email: str) -> bool:
    email_clean = email.lower().strip()
    if not email_clean or "@" not in email_clean:
        return False
    usuario = email_clean.split("@")[0]
    dominio = email_clean.split("@")[1]

    # Não bloqueia e-mails de escritórios contábeis e jurídicos
    if any(c in dominio for c in ["contab", "contabil", "escritorio", "gestao", "advocaci"]):
        return False

    for t in TERMOS_BLOQUEADOS_CNPJ_EMAIL:
        if t in usuario or t in dominio:
            if t == "roupas" and ("group" in usuario or "group" in dominio):
                continue
            if t == "burger" and "brandenburger" in usuario:
                continue
            return True
    return False


def lead_eh_intruso_cnpj(nome: str, email: str) -> bool:
    nome_norm = f" {nome.lower()} "

    # 1. Se o e-mail de contato revelar comércio/serviço intruso, descarta na hora:
    if email_eh_intruso_cnpj(email):
        return True

    # 2. Se o nome contém termos explícitos de outros comércios/serviços, descarta:
    for b in TERMOS_BLOQUEADOS_CNPJ_NOME:
        if re.search(b, nome_norm):
            return True

    return False

_MAPA_MUNICIPIOS: Optional[Dict[str, Dict[str, str]]] = None


def carregar_mapa_municipios() -> Dict[str, Dict[str, str]]:
    global _MAPA_MUNICIPIOS
    if _MAPA_MUNICIPIOS is None:
        if MUNICIPIOS_RECEITA_PATH.exists():
            with MUNICIPIOS_RECEITA_PATH.open("r", encoding="utf-8") as f:
                _MAPA_MUNICIPIOS = json.load(f)
        else:
            _MAPA_MUNICIPIOS = {}
    return _MAPA_MUNICIPIOS


def parse_regiao(regiao: str) -> Tuple[str, str]:
    partes = [p.strip() for p in regiao.replace("-", ",").split(",") if p.strip()]
    if len(partes) >= 2:
        return partes[0], partes[1].upper()
    return regiao.strip(), "SP"


def obter_codigo_municipio(cidade: str, uf: str) -> Optional[str]:
    mapa = carregar_mapa_municipios()
    uf_dict = mapa.get(uf.upper(), {})
    if cidade in uf_dict:
        return uf_dict[cidade]
    cidade_lower = cidade.lower().strip()
    for c, cod in uf_dict.items():
        if c.lower().strip() == cidade_lower:
            return cod
    return None


def formatar_cnpj(cnpj_raw: str) -> str:
    digits = "".join(c for c in str(cnpj_raw or "") if c.isdigit()).zfill(14)
    if len(digits) == 14:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    return cnpj_raw or ""


def formatar_telefone_com_ddd(ddd: str, numero: str) -> str:
    d = "".join(c for c in str(ddd or "") if c.isdigit())
    n = "".join(c for c in str(numero or "") if c.isdigit())
    if not n or not d:
        return ""
    if len(set(n)) <= 1 or not any(c in "123456789" for c in n):
        return ""
    if d.startswith("0"):
        d = d.lstrip("0")
    if len(d) > 2:
        d = d[:2]
    if len(d) != 2 or not (11 <= int(d) <= 99):
        return ""
    if n.startswith("55") and len(n) >= 12:
        n = n[2:]
    if len(n) in (8, 9):
        if len(n) == 9:
            return f"({d}) {n[0]} {n[1:5]}-{n[5:]}"
        return f"({d}) {n[:4]}-{n[4:]}"
    if len(n) >= 10:
        d_extra = n[:2]
        resto = n[2:]
        if len(resto) == 9:
            return f"({d_extra}) {resto[0]} {resto[1:5]}-{resto[5:]}"
        return f"({d_extra}) {resto[:4]}-{resto[4:]}"
    return f"({d}) {n}"


def classificar_lead_cnpj(loja: Dict) -> Dict:
    tel1 = str(loja.get("telefone", "") or "")
    tel2 = str(loja.get("telefone2", "") or "")
    email = str(loja.get("email", "") or "").strip()

    # Filtra placeholders (apenas zeros ou inválidos)
    digits_tel = "".join(c for c in tel1 if c.isdigit())
    if len(set(digits_tel)) <= 1 or not any(c in "123456789" for c in digits_tel):
        digits_tel = ""
        tel1 = ""

    digits_tel2 = "".join(c for c in tel2 if c.isdigit())
    if len(set(digits_tel2)) <= 1 or not any(c in "123456789" for c in digits_tel2):
        digits_tel2 = ""
        tel2 = ""

    # Se for celular de 8 dígitos antigo (iniciando em 6, 7, 8 ou 9), acrescenta o 9
    if len(digits_tel) == 10 and digits_tel[2] in ("6", "7", "8", "9"):
        digits_tel = f"{digits_tel[:2]}9{digits_tel[2:]}"
    if len(digits_tel2) == 10 and digits_tel2[2] in ("6", "7", "8", "9"):
        digits_tel2 = f"{digits_tel2[:2]}9{digits_tel2[2:]}"

    eh_celular = False
    numero_wa = ""
    tel_alternativo = ""

    # Verifica se telefone 1 ou telefone 2 é celular válido (DDD + 9 dígitos)
    if len(digits_tel) == 11 and digits_tel[2] == "9":
        eh_celular = True
        numero_wa = digits_tel
        tel_alternativo = tel2 if tel2 != tel1 else ""
    elif len(digits_tel2) == 11 and digits_tel2[2] == "9":
        eh_celular = True
        numero_wa = digits_tel2
        tel_alternativo = tel1 if tel1 != tel2 else ""
    else:
        tel_alternativo = tel1 or tel2

    if eh_celular and numero_wa:
        status_contato = "🔥 WhatsApp"
        link_whatsapp = f"https://wa.me/55{numero_wa}"
        loja["whatsapp"] = formatar_telefone_com_ddd(numero_wa[:2], numero_wa[2:])
        loja["telefone"] = tel_alternativo
    elif digits_tel or digits_tel2:
        status_contato = "📞 Telefone Fixo"
        link_whatsapp = ""
        loja["whatsapp"] = ""
        loja["telefone"] = tel_alternativo
    elif email:
        status_contato = "✉️ E-mail"
        link_whatsapp = ""
        loja["whatsapp"] = ""
        loja["telefone"] = ""
    else:
        status_contato = "⚪ Sem Contato"
        link_whatsapp = ""
        loja["whatsapp"] = ""
        loja["telefone"] = ""

    score = 90 if eh_celular else (60 if loja["telefone"] else (40 if email else 10))

    loja["status_contato"] = status_contato
    loja["tipo_contato"] = status_contato
    loja["link_whatsapp"] = link_whatsapp
    loja["score"] = score
    loja["classificacao"] = status_contato
    return loja


def normalizar_cnaes(nicho: str, cnae_custom: Optional[str] = None) -> List[str]:
    cnaes = []
    if nicho == "custom" and cnae_custom:
        cnaes = [re.sub(r"\D", "", c.strip()) for c in cnae_custom.replace(";", ",").split(",") if c.strip()]
    elif nicho in NICHOS:
        cnaes = NICHOS[nicho]["cnaes"]
    else:
        cnaes = NICHOS["imoveis"]["cnaes"]
    return [c for c in cnaes if c]


def consultar_chunk_duckdb(
    chunk_index: int,
    uf: Optional[str],
    codigos_municipio: Optional[List[str]],
    cnaes: List[str],
    max_por_cidade: int,
) -> List[Dict]:
    parquet_url = f"{PARQUET_BASE_URL}/estabelecimentos{chunk_index}.parquet"
    con = duckdb.connect()
    try:
        con.execute("SET preserve_insertion_order=false;")
        con.execute("SET enable_http_metadata_cache=true;")
        con.execute("SET enable_object_cache=true;")
        con.execute("SET parquet_metadata_cache=true;")
        cnaes_sql = ", ".join(f"'{c}'" for c in cnaes)
        where_conds = [
            f"cnae_fiscal_principal IN ({cnaes_sql})",
            "situacao_cadastral = '02'",
        ]
        if uf:
            where_conds.append(f"uf = '{uf}'")
        if codigos_municipio and len(codigos_municipio) < 4000:
            mun_sql = ", ".join(f"'{m}'" for m in codigos_municipio)
            where_conds.append(f"municipio IN ({mun_sql})")

        where_str = " AND ".join(where_conds)

        query = f"""
            WITH ranked AS (
                SELECT 
                    cnpj_basico || cnpj_ordem || cnpj_dv as cnpj_raw,
                    nome_fantasia,
                    tipo_logradouro,
                    logradouro,
                    numero,
                    complemento,
                    bairro,
                    cep,
                    uf,
                    municipio as cod_municipio,
                    ddd1,
                    telefone1,
                    ddd2,
                    telefone2,
                    correio_eletronico,
                    cnae_fiscal_principal,
                    data_inicio_atividade,
                    ROW_NUMBER() OVER (
                        PARTITION BY municipio 
                        ORDER BY 
                            CASE WHEN ddd1 IS NOT NULL AND telefone1 IS NOT NULL AND telefone1 != '' THEN 0 ELSE 1 END,
                            data_inicio_atividade DESC
                    ) as rnk
                FROM read_parquet('{parquet_url}')
                WHERE {where_str}
            )
            SELECT * FROM ranked WHERE rnk <= {max_por_cidade}
        """
        rows = con.execute(query).fetchall()
        resultados = []
        for r in rows:
            resultados.append({
                "cnpj_raw": r[0],
                "nome_fantasia": r[1] or "",
                "tipo_logradouro": r[2] or "",
                "logradouro": r[3] or "",
                "numero": r[4] or "",
                "complemento": r[5] or "",
                "bairro": r[6] or "",
                "cep": r[7] or "",
                "uf": r[8] or "",
                "cod_municipio": r[9] or "",
                "ddd1": r[10] or "",
                "telefone1": r[11] or "",
                "ddd2": r[12] or "",
                "telefone2": r[13] or "",
                "correio_eletronico": r[14] or "",
                "cnae_fiscal_principal": r[15] or "",
                "data_inicio_atividade": r[16] or "",
            })
        return resultados
    finally:
        con.close()


async def executar_varredura_cnpj(
    regioes: List[str],
    nicho: str,
    cnae_custom: Optional[str],
    max_lojas: int,
    output_dir: Path,
    progress_cb: Optional[Callable[[Dict], None]] = None,
    permitir_repetidas: bool = True,
) -> Dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    cnaes = normalizar_cnaes(nicho, cnae_custom)
    nicho_info = NICHOS.get(nicho, NICHOS["imoveis"])
    nicho_nome = nicho_info["nome"]

    # Agrupa cidades por UF
    cidades_por_uf: Dict[str, Dict[str, str]] = {}
    for reg in regioes:
        cidade, uf = parse_regiao(reg)
        cod = obter_codigo_municipio(cidade, uf)
        if cod:
            if uf not in cidades_por_uf:
                cidades_por_uf[uf] = {}
            cidades_por_uf[uf][cod] = f"{cidade}, {uf}"

    total_cidades_ativas = sum(len(c) for c in cidades_por_uf.values())
    if total_cidades_ativas == 0:
        # Fallback para São Paulo, SP
        cidades_por_uf = {"SP": {"7107": "São Paulo, SP"}}
        total_cidades_ativas = 1

    if progress_cb:
        progress_cb({
            "type": "total",
            "total": total_cidades_ativas,
            "message": f"Iniciando Motor Receita CNPJ em {total_cidades_ativas} cidades ({nicho_nome})...",
        })

    leads_coletados_por_cidade: Dict[str, List[Dict]] = {
        f"{cidade}, {uf}": [] for uf, cidades in cidades_por_uf.items() for cod, cidade_uf in cidades.items()
    }
    cnpjs_vistos: Set[str] = set()
    total_coletados = 0

    # Mapeamento global cod_municipio -> f"{cidade}, {uf}"
    cod_para_cidade_uf: Dict[str, str] = {
        cod: cidade_uf for uf, cidades in cidades_por_uf.items() for cod, cidade_uf in cidades.items()
    }

    def adicionar_registro(reg: Dict, nome_cidade_uf: str) -> bool:
        nonlocal total_coletados
        lista_cidade = leads_coletados_por_cidade.setdefault(nome_cidade_uf, [])
        if len(lista_cidade) >= max_lojas:
            return False

        cnpj_formatado = formatar_cnpj(reg["cnpj_raw"])
        if cnpj_formatado in cnpjs_vistos and not permitir_repetidas:
            return False

        cnpjs_vistos.add(cnpj_formatado)

        partes_end = [
            f"{reg['tipo_logradouro']} {reg['logradouro']}".strip(),
            reg['numero'],
            reg['complemento'],
        ]
        end_rua = ", ".join(p for p in partes_end if p and not p.startswith("---")).strip(", ")
        bairro = reg['bairro'].strip()
        if bairro and end_rua:
            endereco_completo = f"{end_rua} - {bairro}"
        elif bairro:
            endereco_completo = bairro
        else:
            endereco_completo = end_rua

        tel1_formatado = formatar_telefone_com_ddd(reg["ddd1"], reg["telefone1"])
        tel2_formatado = formatar_telefone_com_ddd(reg["ddd2"], reg["telefone2"])

        nome_raw = reg["nome_fantasia"].strip()
        # Higieniza placeholders da Receita Federal (ex: ************, ----------, etc)
        letras_nome = re.sub(r"[^a-zA-ZÀ-ÿ]", "", nome_raw)
        if len(letras_nome) < 3:
            nome_exibicao = f"Imobiliária (CNPJ {cnpj_formatado})"
        else:
            nome_exibicao = nome_raw

        # Pente Fino Anti-Ruído RIGOROSO: se for detectado comércio/serviço intruso, descarta imediatamente!
        email_clean = reg["correio_eletronico"].lower().strip()
        if lead_eh_intruso_cnpj(nome_exibicao, email_clean):
            return False

        lead = {
            "regiao": nome_cidade_uf,
            "nome": nome_exibicao,
            "cnpj": cnpj_formatado,
            "email": reg["correio_eletronico"].lower().strip(),
            "telefone": tel1_formatado,
            "telefone2": tel2_formatado,
            "whatsapp": "",
            "endereco": endereco_completo,
            "bairro": reg["bairro"].strip(),
            "cep": reg["cep"].strip(),
            "categoria": f"CNAE {reg['cnae_fiscal_principal']}",
            "data_abertura": reg["data_inicio_atividade"].strip(),
            "site": "",
            "horario": "Horário Comercial",
            "nota": "",
            "url": f"https://cnpja.com/consulta/{reg['cnpj_raw']}",
        }

        lead = classificar_lead_cnpj(lead)
        lista_cidade.append(lead)
        total_coletados += 1
        return True

    # Itera chunks da Receita Federal (0 a 9) até preencher as metas de cada cidade
    CHUNK_ORDER = [1, 2, 3, 4, 5, 6, 7, 8, 9, 0]
    chunks_concluidos = 0
    if max_lojas <= 5:
        max_chunks_para_consultar = 3
    elif max_lojas <= 10:
        max_chunks_para_consultar = 4
    elif max_lojas <= 25:
        max_chunks_para_consultar = 5
    else:
        max_chunks_para_consultar = 6

    for step_idx, chunk_idx in enumerate(CHUNK_ORDER[:max_chunks_para_consultar], start=1):
        total_antes_chunk = total_coletados
        # Verifica se todas as cidades já atingiram max_lojas
        todas_cheias = all(
            len(leads_coletados_por_cidade.get(cid, [])) >= max_lojas
            for cid in leads_coletados_por_cidade
        )
        if todas_cheias:
            break

        if len(cidades_por_uf) >= 4:
            # Modo Nacional / Multi-Estados: 1 query ultrarrápida por chunk cobrindo todo o Brasil
            codigos_pendentes = [
                cod for cod, nome_cid in cod_para_cidade_uf.items()
                if len(leads_coletados_por_cidade.get(nome_cid, [])) < max_lojas
            ]
            if not codigos_pendentes:
                break

            if progress_cb:
                progress_cb({
                    "type": "message",
                    "message": f"Consultando base da Receita Federal (Lote {step_idx}/{max_chunks_para_consultar} - Brasil)...",
                })

            try:
                registros = await asyncio.wait_for(
                    asyncio.to_thread(
                        consultar_chunk_duckdb,
                        chunk_idx,
                        None,
                        codigos_pendentes if len(codigos_pendentes) < 3000 else None,
                        cnaes,
                        max_lojas,
                    ),
                    timeout=90.0,
                )
            except Exception:
                registros = []

            for reg in registros:
                cod_mun = reg["cod_municipio"]
                nome_cid = cod_para_cidade_uf.get(cod_mun)
                if nome_cid:
                    adicionar_registro(reg, nome_cid)
        else:
            # Modo Estado Único ou Poucos Estados
            for uf, cidades_map in cidades_por_uf.items():
                codigos_pendentes = [
                    cod for cod, nome_cid in cidades_map.items()
                    if len(leads_coletados_por_cidade.get(nome_cid, [])) < max_lojas
                ]
                if not codigos_pendentes:
                    continue

                if progress_cb:
                    progress_cb({
                        "type": "message",
                        "message": f"Consultando base da Receita Federal em {uf} (Lote {step_idx}/{max_chunks_para_consultar})...",
                    })

                try:
                    registros = await asyncio.wait_for(
                        asyncio.to_thread(
                            consultar_chunk_duckdb,
                            chunk_idx,
                            uf,
                            codigos_pendentes,
                            cnaes,
                            max_lojas,
                        ),
                        timeout=60.0,
                    )
                except Exception:
                    registros = []

                for reg in registros:
                    cod_mun = reg["cod_municipio"]
                    nome_cidade_uf = cidades_map.get(cod_mun, f"{uf} - {cod_mun}")
                    adicionar_registro(reg, nome_cidade_uf)

        chunks_concluidos += 1
        cidades_com_dados = sum(1 for leads in leads_coletados_por_cidade.values() if len(leads) > 0)
        if progress_cb:
            msg = f"Base Receita: {cidades_com_dados}/{total_cidades_ativas} cidades ({total_coletados} empresas ativas)"
            progress_cb({
                "type": "item_done",
                "current": cidades_com_dados,
                "total": total_cidades_ativas,
                "message": msg,
            })

        novos_no_chunk = total_coletados - total_antes_chunk
        if step_idx >= 3 and novos_no_chunk < 25:
            break

    # Compila todos os leads
    todos_leads: List[Dict] = []
    for leads in leads_coletados_por_cidade.values():
        todos_leads.extend(leads)

    # Ordena de forma organizada: Estado (UF), Cidade, e leads com WhatsApp primeiro
    def chave_ordenacao(item: Dict):
        reg = item.get("regiao", "")
        partes = reg.split(",")
        cidade = partes[0].strip() if partes else ""
        uf = partes[1].strip() if len(partes) > 1 else ""
        status = str(item.get("status_contato") or item.get("classificacao") or "")
        peso = 0 if "WhatsApp" in status else (1 if "Fixo" in status or "Telefone" in status else (2 if "E-mail" in status else 3))
        return (uf, cidade, peso, item.get("nome", ""))

    todos_leads.sort(key=chave_ordenacao)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    data_arquivo = datetime.now().strftime("%d-%m-%Y")
    nome_base = f"Varredura-CNPJ {nicho.title()} {data_arquivo}"
    csv_path = output_dir / f"{nome_base}.csv"
    excel_path = output_dir / f"{nome_base}.xlsx"

    from scraper import montar_resumo, salvar_csv, salvar_excel
    salvar_csv(todos_leads, csv_path)
    await asyncio.to_thread(salvar_excel, todos_leads, excel_path)

    resumo = montar_resumo(todos_leads, regioes)

    return {
        "dados": todos_leads,
        "resumo": resumo,
        "csv_path": str(csv_path),
        "excel_path": str(excel_path),
        "log_path": "",
        "duplicadas_ignoradas": 0,
        "repetidas_permitidas": permitir_repetidas,
        "historico_total": len(todos_leads),
    }
