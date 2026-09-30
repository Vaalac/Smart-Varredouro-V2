import asyncio
import csv
import json
import os
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

import httpx
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BASE_DIR / ".playwright-browsers"))

from municipios_br import REGIOES_DISPONIVEIS, formatar_termo_busca, validar_regiao
from supabase_history import carregar_lojas as carregar_historico_supabase
from supabase_history import salvar_lojas as salvar_historico_supabase
from supabase_history import supabase_ativo

MAX_WORKERS = 5
MAX_SEARCH_CONCURRENCY = 3
CAMPOS = [
    "classificacao",
    "score",
    "link_whatsapp",
    "tipo_contato",
    "regiao",
    "nome",
    "telefone",
    "whatsapp",
    "endereco",
    "categoria",
    "horario",
    "site",
    "nota",
    "url",
]
HISTORICO_ARQUIVO = "lojas_ja_coletadas.csv"
TERMOS_MOVEIS = [
    "movel", "moveis", "móveis", "mobiliario", "mobiliário",
    "decoracao", "decoração", "colchoes", "colchões", "estofado",
    "estofados", "sofa", "sofá", "planejados", "marcenaria",
    "cama", "mesa", "cadeira", "armario", "armário", "guarda roupa",
    "guarda-roupa", "rack", "decor", "casa"
]
TERMOS_BLOQUEADOS = [
    "supermercado", "mercado", "hipermercado", "mercearia",
    "departamento", "eletrodomestico", "eletrodoméstico", "eletronico",
    "eletrônico", "farmacia", "farmácia", "padaria", "restaurante",
    "lanchonete", "shopping", "posto de gasolina", "autopecas",
    "autopeças", "material de construcao", "material de construção",
    "conveniencia", "conveniência", "variedades", "roupa", "calcados",
    "calçados", "pet shop", "academia", "oficina", "hotel"
]

ProgressCallback = Optional[Callable[[Dict], None]]


def formatar_telefone(numero: str) -> str:
    if not numero:
        return ""

    digits = "".join(c for c in numero if c.isdigit())

    if digits.startswith("55") and len(digits) >= 12:
        digits = digits[2:]

    if digits.startswith("0") and len(digits) in (11, 12):
        digits = digits[1:]

    if len(digits) == 11:
        ddd = digits[:2]
        resto = digits[2:]
        return f"({ddd}) {resto[0]} {resto[1:5]}-{resto[5:]}"

    if len(digits) == 10:
        ddd = digits[:2]
        resto = digits[2:]
        return f"({ddd}) {resto[:4]}-{resto[4:]}"

    return numero


def classificar_lead(loja: Dict) -> Dict:
    """
    Analisa os dados da loja coletada e calcula:
    - tipo_contato: 'Celular / WhatsApp', 'Telefone Fixo' ou 'Sem Telefone'
    - link_whatsapp: URL wa.me se houver celular ou whatsapp explícito
    - score: pontuação de 0 a 100 baseada na maturidade comercial do lead
    - classificacao: '🔥 Quente', '🟡 Morno' ou '⚪ Frio'
    """
    telefone = str(loja.get("telefone", "") or "")
    whatsapp = str(loja.get("whatsapp", "") or "")
    site = str(loja.get("site", "") or "")
    nota_str = str(loja.get("nota", "") or "")

    digits_tel = "".join(c for c in telefone if c.isdigit())
    digits_wa = "".join(c for c in whatsapp if c.isdigit())

    if digits_tel.startswith("55") and len(digits_tel) >= 12:
        digits_tel = digits_tel[2:]
    if digits_tel.startswith("0") and len(digits_tel) in (11, 12):
        digits_tel = digits_tel[1:]

    if digits_wa.startswith("55") and len(digits_wa) >= 12:
        digits_wa = digits_wa[2:]
    if digits_wa.startswith("0") and len(digits_wa) in (11, 12):
        digits_wa = digits_wa[1:]

    eh_celular = False
    numero_wa = ""

    if digits_wa and len(digits_wa) in (10, 11):
        eh_celular = True
        numero_wa = digits_wa
    elif len(digits_tel) == 11 and digits_tel[2] == "9":
        eh_celular = True
        numero_wa = digits_tel

    if eh_celular and numero_wa:
        tipo_contato = "Celular / WhatsApp"
        link_whatsapp = f"https://wa.me/55{numero_wa}"
        if not loja.get("whatsapp"):
            loja["whatsapp"] = formatar_telefone(numero_wa)
    elif len(digits_tel) == 10:
        tipo_contato = "Telefone Fixo"
        link_whatsapp = ""
    elif digits_tel:
        tipo_contato = "Telefone"
        link_whatsapp = ""
    else:
        tipo_contato = "Sem Telefone"
        link_whatsapp = ""

    score = 0

    # 1. Contato direto (até 50 pontos)
    if eh_celular:
        score += 50
    elif tipo_contato == "Telefone Fixo":
        score += 25
    elif digits_tel:
        score += 15

    # 2. Presença digital / Site / Redes (até 25 pontos)
    site_lower = site.lower()
    if site:
        if any(term in site_lower for term in ["instagram.com", "facebook.com", "linktr.ee"]):
            score += 20
        else:
            score += 25

    # 3. Avaliação no Google Maps (até 25 pontos)
    try:
        nota = float(nota_str.replace(",", "."))
        if nota >= 4.5:
            score += 25
        elif nota >= 4.0:
            score += 18
        elif nota >= 3.0:
            score += 10
        else:
            score += 0
    except (ValueError, TypeError):
        score += 5

    if score >= 70:
        classificacao = "🔥 Quente"
    elif score >= 40:
        classificacao = "🟡 Morno"
    else:
        classificacao = "⚪ Frio"

    loja["tipo_contato"] = tipo_contato
    loja["link_whatsapp"] = link_whatsapp
    loja["score"] = score
    loja["classificacao"] = classificacao

    return loja


def limpar_texto(texto: str) -> str:
    if not texto:
        return ""

    texto = re.sub(r"[\ue000-\uf8ff]", "", str(texto)).strip()
    try:
        return texto.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore").strip()
    except Exception:
        return str(texto).strip()


def log_erro(log_path: Path, mensagem: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {mensagem}\n")


def chave_texto(valor: str) -> str:
    valor = limpar_texto(valor or "").lower()
    valor = re.sub(r"https?://(www\.)?", "", valor)
    valor = re.sub(r"[^a-z0-9]+", " ", valor)
    return re.sub(r"\s+", " ", valor).strip()


def texto_busca(valor: str) -> str:
    valor = limpar_texto(valor or "").lower()
    valor = valor.replace("ã", "a").replace("á", "a").replace("à", "a").replace("â", "a")
    valor = valor.replace("é", "e").replace("ê", "e")
    valor = valor.replace("í", "i")
    valor = valor.replace("ó", "o").replace("ô", "o").replace("õ", "o")
    valor = valor.replace("ú", "u").replace("ü", "u")
    valor = valor.replace("ç", "c")
    return valor


def parece_loja_de_moveis(loja: Dict) -> bool:
    texto = texto_busca(
        " ".join(
            [
                loja.get("nome", ""),
                loja.get("categoria", ""),
                loja.get("site", ""),
                loja.get("url", ""),
            ]
        )
    )

    bloqueado = any(texto_busca(termo) in texto for termo in TERMOS_BLOQUEADOS)
    permitido = any(texto_busca(termo) in texto for termo in TERMOS_MOVEIS)

    return permitido and not bloqueado


def chave_telefone(valor: str) -> str:
    digits = "".join(c for c in (valor or "") if c.isdigit())
    if digits.startswith("55") and len(digits) >= 12:
        digits = digits[2:]
    if digits.startswith("0") and len(digits) in (11, 12):
        digits = digits[1:]
    return digits


def chaves_loja(loja: Dict) -> Set[str]:
    chaves: Set[str] = set()

    url = chave_texto(loja.get("url", ""))
    if url:
        chaves.add(f"url:{url}")

    telefone = chave_telefone(loja.get("telefone", ""))
    if telefone:
        chaves.add(f"tel:{telefone}")

    whatsapp = chave_telefone(loja.get("whatsapp", ""))
    if whatsapp:
        chaves.add(f"tel:{whatsapp}")

    site = chave_texto(loja.get("site", ""))
    if site:
        chaves.add(f"site:{site}")

    nome = chave_texto(loja.get("nome", ""))
    endereco = chave_texto(loja.get("endereco", ""))
    if nome and endereco:
        chaves.add(f"nome_endereco:{nome}|{endereco}")
    elif nome:
        chaves.add(f"nome:{nome}")

    return chaves


def carregar_csv_lojas(path: Path) -> List[Dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []

    try:
        with path.open("r", encoding="utf-8-sig", newline="", errors="replace") as f:
            reader = csv.DictReader(f)
            lojas = []
            for row in reader:
                if row.get("nome") or row.get("url"):
                    d = dict(row)
                    if not d.get("classificacao"):
                        d = classificar_lead(d)
                    lojas.append(d)
            return lojas
    except Exception:
        return []


def carregar_historico(outputs_root: Path) -> Tuple[List[Dict], Set[str]]:
    if supabase_ativo():
        lojas: List[Dict] = carregar_historico_supabase()
    else:
        historico_path = outputs_root / HISTORICO_ARQUIVO
        lojas = carregar_csv_lojas(historico_path)

        for csv_path in outputs_root.glob("*/*.csv"):
            lojas.extend(carregar_csv_lojas(csv_path))

    chaves: Set[str] = set()
    unicas: List[Dict] = []
    for loja in lojas:
        if not parece_loja_de_moveis(loja):
            continue

        loja_chaves = chaves_loja(loja)
        if not loja_chaves or chaves.intersection(loja_chaves):
            continue
        chaves.update(loja_chaves)
        unicas.append({campo: loja.get(campo, "") for campo in CAMPOS})

    return unicas, chaves


def salvar_historico(outputs_root: Path, lojas: List[Dict]) -> None:
    if supabase_ativo():
        salvar_historico_supabase(lojas)
        return

    historico_path = outputs_root / HISTORICO_ARQUIVO
    salvar_csv(lojas, historico_path)


def filtrar_lojas_novas(dados: List[Dict], chaves_historico: Set[str]) -> Tuple[List[Dict], int]:
    novas: List[Dict] = []
    chaves_vistas = set(chaves_historico)
    duplicadas = 0

    for loja in dados:
        loja_chaves = chaves_loja(loja)
        if loja_chaves and chaves_vistas.intersection(loja_chaves):
            duplicadas += 1
            continue

        novas.append(loja)
        chaves_vistas.update(loja_chaves)

    return novas, duplicadas


async def buscar_links_regiao(page, regiao: str, max_lojas: int, log_path: Path) -> List[str]:
    termo = formatar_termo_busca(regiao).replace(" ", "+")
    busca = f"lojas+de+moveis+{termo}"
    url = f"https://www.google.com/maps/search/{busca}"

    for tentativa in range(3):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            break
        except Exception as e:
            if tentativa == 2:
                log_erro(log_path, f"Falha ao carregar regiao {regiao}: {e}")
                return []
            await asyncio.sleep(1)

    try:
        await page.wait_for_selector('div[role="feed"], a[href*="/maps/place/"]', timeout=8000)
    except Exception:
        pass

    conteudo = await page.content()
    if "captcha" in conteudo.lower():
        log_erro(log_path, f"Captcha detectado em {regiao}.")
        return []

    # Verificar se ja possui links suficientes antes de rolar desnecessariamente
    links_iniciais = await page.locator('a[href*="/maps/place/"]').all()
    if len(links_iniciais) < max_lojas:
        max_scrolls = max(2, min(10, (max_lojas - len(links_iniciais) + 2) // 3))
        last_count = len(links_iniciais)
        no_growth_streak = 0

        for _ in range(max_scrolls):
            try:
                lista = page.locator('div[role="feed"]')
                if await lista.count() > 0:
                    await lista.first.evaluate("el => el.scrollBy(0, 1200)")
                else:
                    await page.evaluate("window.scrollBy(0, 1200)")
            except Exception:
                await page.evaluate("window.scrollBy(0, 1200)")

            await asyncio.sleep(0.35)
            current_count = await page.locator('a[href*="/maps/place/"]').count()
            if current_count >= max_lojas:
                break

            # Se duas rolagens seguidas não trouxeram novos resultados, o feed acabou
            if current_count == last_count:
                no_growth_streak += 1
                if no_growth_streak >= 2:
                    break
            else:
                no_growth_streak = 0
                last_count = current_count

    links = await page.locator('a[href*="/maps/place/"]').all()
    hrefs = []
    for link in links:
        href = await link.get_attribute("href")
        if href and href not in hrefs:
            hrefs.append(href)
        if len(hrefs) >= max_lojas:
            break

    return hrefs


async def extrair_detalhes(page, url: str, regiao: str, log_path: Path) -> Optional[Dict]:
    for tentativa in range(2):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            try:
                await page.wait_for_selector("h1", timeout=4500)
            except Exception:
                pass

            dados_raw = await page.evaluate("""() => {
                const h1 = document.querySelector('h1');
                const nome = h1 ? h1.innerText.trim() : '';

                const phoneBtn = document.querySelector('button[data-item-id^="phone"]');
                const phoneAttr = phoneBtn ? (phoneBtn.getAttribute('data-item-id') || '') : '';
                let telefone = phoneAttr.replace('phone:tel:', '').trim();

                let whatsapp = '';
                const waLink = document.querySelector('a[href*="wa.me"], a[href*="api.whatsapp.com"], a[href*="whatsapp.com"]');
                if (waLink) {
                    const href = waLink.getAttribute('href') || '';
                    const match = href.match(/(?:phone=|wa\\.me\\/)(\\+?55\\d{10,11}|\\d{10,11})/);
                    if (match) {
                        whatsapp = match[1].replace('+', '');
                    }
                }

                const addrBtn = document.querySelector('button[data-item-id="address"]');
                let endereco = '';
                if (addrBtn) {
                    endereco = (addrBtn.getAttribute('aria-label') || addrBtn.innerText || '')
                        .replace('Endereço: ', '').replace('Endereco: ', '').replace('Address: ', '').trim();
                }

                const siteLink = document.querySelector('a[data-item-id="authority"]');
                let site = siteLink ? (siteLink.getAttribute('href') || '') : '';

                if (!site) {
                    const socialLink = document.querySelector('a[href*="instagram.com"], a[href*="facebook.com"], a[data-item-id*="social"]');
                    if (socialLink) {
                        site = socialLink.getAttribute('href') || '';
                    }
                }

                let nota = '';
                const ratingEl = document.querySelector('div.F7nice span[aria-hidden="true"], span.ceNzKf, div[jsaction*="pane.rating"]');
                if (ratingEl) {
                    const match = (ratingEl.innerText || '').match(/\\b[1-5][.,]\\d\\b/);
                    if (match) nota = match[0].replace(',', '.');
                }

                const catBtn = document.querySelector('button[jsaction*="category"]');
                const categoria = catBtn ? catBtn.innerText.trim() : '';

                const horEl = document.querySelector('div[data-hide-tooltip-on-mouse-move]');
                const horario = horEl ? horEl.innerText.replace(/[\\ue000-\\uf8ff]/g, '').split('\\n')[0].trim() : '';

                return {
                    nome,
                    telefone,
                    whatsapp,
                    endereco,
                    site,
                    nota,
                    categoria,
                    horario,
                };
            }""")

            if not dados_raw or not dados_raw.get("nome"):
                return None

            return {
                "regiao": regiao,
                "nome": limpar_texto(dados_raw.get("nome", "")),
                "telefone": dados_raw.get("telefone", ""),
                "whatsapp": dados_raw.get("whatsapp", ""),
                "endereco": limpar_texto(dados_raw.get("endereco", "")),
                "categoria": limpar_texto(dados_raw.get("categoria", "")),
                "horario": limpar_texto(dados_raw.get("horario", "")),
                "site": dados_raw.get("site", "") or "",
                "nota": dados_raw.get("nota", ""),
                "url": url,
            }

        except Exception as e:
            if tentativa == 1:
                log_erro(log_path, f"Falha ao extrair {url}: {e}")
            await asyncio.sleep(1)

    return None


async def coletar_lojas_cidade(
    page,
    regiao: str,
    max_lojas: int,
    log_path: Path,
) -> List[Dict]:
    termo = formatar_termo_busca(regiao).replace(" ", "+")
    busca = f"lojas+de+moveis+{termo}"
    url = f"https://www.google.com/maps/search/{busca}"

    for tentativa in range(3):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            break
        except Exception as e:
            if tentativa == 2:
                log_erro(log_path, f"Falha ao carregar regiao {regiao}: {e}")
                return []
            await asyncio.sleep(1)

    try:
        await page.wait_for_selector('div.Nv2PK, div[role="feed"]', timeout=8000)
    except Exception:
        pass

    conteudo = await page.content()
    if "captcha" in conteudo.lower():
        log_erro(log_path, f"Captcha detectado em {regiao}.")
        return []

    # Se precisa de mais que o lote inicial visível (~6), rola suavemente
    cards_count = await page.locator('div.Nv2PK').count()
    if cards_count < max_lojas:
        max_scrolls = max(2, min(8, (max_lojas - cards_count + 2) // 3))
        last_count = cards_count
        no_growth = 0
        for _ in range(max_scrolls):
            try:
                lista = page.locator('div[role="feed"]')
                if await lista.count() > 0:
                    await lista.first.evaluate("el => el.scrollBy(0, 1200)")
                else:
                    await page.evaluate("window.scrollBy(0, 1200)")
            except Exception:
                await page.evaluate("window.scrollBy(0, 1200)")

            await asyncio.sleep(0.3)
            current_count = await page.locator('div.Nv2PK').count()
            if current_count >= max_lojas:
                break
            if current_count == last_count:
                no_growth += 1
                if no_growth >= 2:
                    break
            else:
                no_growth = 0
                last_count = current_count

    # Extração de alta performance diretamente da estrutura dos cards
    lojas_extraidas = await page.evaluate("""(maxCount) => {
        const cards = Array.from(document.querySelectorAll('div.Nv2PK'));
        const itens = [];

        for (const c of cards) {
            if (itens.length >= maxCount) break;

            const a = c.querySelector('a.hfpxzc') || c.querySelector('a[href*="/maps/place/"]');
            const titleEl = c.querySelector('div.qBF1Pd');
            const ratingEl = c.querySelector('span.MW4etd');
            const phoneEl = c.querySelector('span.UsdlK');
            const text = c.innerText || '';

            let telefone = phoneEl ? phoneEl.innerText.trim() : '';
            if (!telefone) {
                const match = text.match(/\\(?\\b\\d{2}\\)?\\s*9?\\d{4}[-\\s]?\\d{4}\\b/);
                if (match) telefone = match[0];
            }

            const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
            let categoria = '';
            let endereco = '';
            let horario = '';

            for (const line of lines) {
                if (line.includes('Loja de') || line.includes('Móveis') || line.includes('Marcenaria') || line.includes('Colchões') || line.includes('Estofados')) {
                    categoria = line.split('·')[0].trim();
                }
                if (line.includes('Rua') || line.includes('Av.') || line.includes('Avenida') || line.includes('Rodovia') || line.includes('Estr.') || line.includes('Praça') || line.includes('Alameda')) {
                    endereco = line.replace(/.*·/, '').trim();
                }
                if (line.includes('Aberto') || line.includes('Fechado')) {
                    horario = line.split('·')[0].trim();
                }
            }

            let nota = ratingEl ? ratingEl.innerText.trim().replace(',', '.') : '';
            const nome = titleEl ? titleEl.innerText.trim() : (a ? a.getAttribute('aria-label') : '');
            const url = a ? (a.getAttribute('href') || '') : '';

            if (nome && url) {
                itens.push({
                    nome,
                    telefone,
                    whatsapp: '',
                    endereco,
                    categoria,
                    horario,
                    site: '',
                    nota,
                    url
                });
            }
        }
        return itens;
    }""", max_lojas)

    lojas_cidade = []
    for l in lojas_extraidas:
        l["regiao"] = regiao
        for campo in ["nome", "endereco", "categoria", "horario", "site", "url", "regiao"]:
            l[campo] = limpar_texto(l.get(campo, ""))

        if not parece_loja_de_moveis(l):
            continue

        l["telefone"] = formatar_telefone(l.get("telefone", ""))
        l = classificar_lead(l)
        lojas_cidade.append(l)

    # Fallback direcionado: para lojas que não trouxeram telefone no card, abre rapidamente os detalhes
    for loja in lojas_cidade:
        if not loja.get("telefone") and loja.get("url"):
            detalhes = await extrair_detalhes(page, loja["url"], regiao, log_path)
            if detalhes:
                if detalhes.get("telefone"):
                    loja["telefone"] = formatar_telefone(detalhes["telefone"])
                if detalhes.get("site"):
                    loja["site"] = detalhes["site"]
                if detalhes.get("whatsapp"):
                    loja["whatsapp"] = formatar_telefone(detalhes["whatsapp"])
                loja = classificar_lead(loja)

    return lojas_cidade


HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def safe_get(lst, idx, default=None):
    try:
        if isinstance(lst, list) and 0 <= idx < len(lst):
            val = lst[idx]
            return val if val is not None else default
    except Exception:
        pass
    return default


def extrair_loja_payload(p: list, regiao: str) -> Optional[Dict]:
    if not isinstance(p, list) or len(p) < 15:
        return None
    nome = safe_get(p, 11, "")
    if not nome or not isinstance(nome, str):
        return None

    categorias = safe_get(p, 13, [])
    categoria = (
        categorias[0]
        if isinstance(categorias, list) and len(categorias) > 0 and isinstance(categorias[0], str)
        else ""
    )

    endereco = safe_get(p, 39, "") or safe_get(p, 18, "")
    if not isinstance(endereco, str):
        endereco = ""

    p4 = safe_get(p, 4, [])
    nota = str(safe_get(p4, 7, "")) if isinstance(p4, list) else ""
    p37 = safe_get(p, 37, [])
    reviews = safe_get(p37, 1, 0) if isinstance(p37, list) else 0

    p7 = safe_get(p, 7, [])
    site = safe_get(p7, 0, "") if isinstance(p7, list) else ""
    if not isinstance(site, str):
        site = ""

    telefone = ""
    p178 = safe_get(p, 178, [])
    if isinstance(p178, list) and len(p178) > 0:
        first_tel = safe_get(p178, 0, [])
        if isinstance(first_tel, list) and len(first_tel) > 0:
            tel_val = safe_get(first_tel, 0, "")
            if isinstance(tel_val, str):
                telefone = tel_val

    place_id = safe_get(p, 78, "")
    url = f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id and isinstance(place_id, str) else ""

    horario = ""
    p203 = safe_get(p, 203, [])
    if isinstance(p203, list) and len(p203) > 0:
        h0 = safe_get(p203, 0, [])
        if isinstance(h0, list) and len(h0) > 0:
            h_sub = safe_get(h0, 0, [])
            if isinstance(h_sub, list) and len(h_sub) > 3:
                h_times = safe_get(h_sub, 3, [])
                if isinstance(h_times, list) and len(h_times) > 0:
                    t_str = safe_get(h_times[0], 0, "")
                    if isinstance(t_str, str):
                        horario = t_str

    loja = {
        "regiao": regiao,
        "nome": limpar_texto(nome),
        "categoria": limpar_texto(categoria),
        "endereco": limpar_texto(endereco),
        "horario": limpar_texto(horario),
        "nota": nota,
        "reviews": reviews,
        "site": limpar_texto(site),
        "telefone": formatar_telefone(telefone),
        "whatsapp": "",
        "url": url,
    }

    if not parece_loja_de_moveis(loja):
        return None

    return classificar_lead(loja)


async def coletar_lojas_cidade_http(
    client: httpx.AsyncClient, cidade: str, max_lojas: int, log_path: Path
) -> List[Dict]:
    termo = formatar_termo_busca(cidade).replace(" ", "+")
    busca = f"lojas+de+moveis+{termo}"
    url = f"https://www.google.com/maps/search/{busca}"
    try:
        r = await client.get(url, timeout=14.0)
        if r.status_code != 200:
            return []
        links = re.findall(r'href="(/search\?tbm=map[^"]+)"', r.text)
        if not links:
            return []
        ep_url = "https://www.google.com" + links[0].replace("&amp;", "&")
        r2 = await client.get(ep_url, timeout=14.0)
        if r2.status_code != 200:
            return []
        body = r2.text
        if body.startswith(")]}'"):
            body = body[body.find("\n") + 1 :]
        data = json.loads(body)
        d64 = data[64] if len(data) > 64 and isinstance(data[64], list) else []
        lojas = []
        for item in d64:
            if isinstance(item, list) and len(item) > 1 and isinstance(item[1], list):
                l = extrair_loja_payload(item[1], cidade)
                if l:
                    lojas.append(l)
                    if len(lojas) >= max_lojas:
                        break
        return lojas
    except Exception as e:
        registrar_erro(log_path, f"Falha HTTP ao buscar {cidade}: {e}")
        return []


def salvar_csv(dados: List[Dict], arquivo: Path) -> None:
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    with arquivo.open("w", newline="", encoding="utf-8-sig", errors="replace") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(dados)


def salvar_excel(dados: List[Dict], arquivo: Path) -> None:
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lojas de Móveis"

    cabecalhos = [
        "Classificação",
        "Score",
        "Link WhatsApp",
        "Tipo Contato",
        "Região",
        "Nome",
        "Telefone",
        "WhatsApp",
        "Endereço",
        "Categoria",
        "Horário",
        "Site",
        "Nota",
        "URL",
    ]
    chaves = CAMPOS

    header_fill = PatternFill("solid", fgColor="1F3864")
    header_font = Font(bold=True, color="FFFFFF")

    fill_quente = PatternFill("solid", fgColor="DCFCE7")
    fill_morno = PatternFill("solid", fgColor="FEF3C7")
    fill_frio = PatternFill("solid", fgColor="F3F4F6")

    font_quente = Font(bold=True, color="166534")
    font_morno = Font(bold=True, color="92400E")
    font_frio = Font(bold=False, color="4B5563")
    font_link = Font(color="0563C1", underline="single")

    for col, cab in enumerate(cabecalhos, 1):
        cell = ws.cell(row=1, column=col, value=cab)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_idx, loja in enumerate(dados, 2):
        for col_idx, chave in enumerate(chaves, 1):
            val = loja.get(chave, "")
            cell = ws.cell(row=row_idx, column=col_idx, value=val)

            if chave == "classificacao":
                cell.alignment = Alignment(horizontal="center", vertical="center")
                if "Quente" in str(val):
                    cell.fill = fill_quente
                    cell.font = font_quente
                elif "Morno" in str(val):
                    cell.fill = fill_morno
                    cell.font = font_morno
                elif "Frio" in str(val):
                    cell.fill = fill_frio
                    cell.font = font_frio
            elif chave in ("score", "tipo_contato", "nota"):
                cell.alignment = Alignment(horizontal="center", vertical="center")

            if chave in ("link_whatsapp", "site", "url") and str(val).startswith("http"):
                cell.hyperlink = val
                cell.font = font_link

    larguras = [16, 10, 36, 20, 22, 35, 18, 18, 45, 25, 20, 35, 8, 50]
    for col, largura in enumerate(larguras, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = largura

    ws.freeze_panes = "A2"
    wb.save(arquivo)


def tratar_resultados(resultados: List[Dict]) -> List[Dict]:
    vistos_nome = set()
    unicos = []

    for d in resultados:
        for campo in ["nome", "endereco", "categoria", "horario", "site", "url", "regiao"]:
            d[campo] = limpar_texto(d.get(campo, ""))

        if not parece_loja_de_moveis(d):
            continue

        chave = d.get("nome", "").lower().strip()
        if not chave or chave in vistos_nome:
            continue

        vistos_nome.add(chave)
        d["telefone"] = formatar_telefone(d.get("telefone", ""))
        d["whatsapp"] = formatar_telefone(d.get("whatsapp", ""))

        d = classificar_lead(d)

        unicos.append(d)

    def chave_ordenacao(item: Dict):
        score = item.get("score", 0)
        try:
            nota = float(str(item.get("nota") or "0").replace(",", "."))
        except Exception:
            nota = 0.0
        return (score, nota)

    unicos.sort(key=chave_ordenacao, reverse=True)
    return unicos


def montar_resumo(dados: List[Dict], regioes: List[str]) -> Dict:
    total = len(dados)
    quentes = sum(1 for d in dados if "Quente" in str(d.get("classificacao", "")))
    mornos = sum(1 for d in dados if "Morno" in str(d.get("classificacao", "")))
    frios = sum(1 for d in dados if "Frio" in str(d.get("classificacao", "")))
    com_whatsapp = sum(1 for d in dados if d.get("link_whatsapp") or d.get("whatsapp"))
    com_telefone = sum(1 for d in dados if d.get("telefone"))
    com_site = sum(1 for d in dados if d.get("site"))

    por_regiao = {regiao: sum(1 for d in dados if d.get("regiao") == regiao) for regiao in regioes}

    return {
        "total": total,
        "quentes": quentes,
        "mornos": mornos,
        "frios": frios,
        "com_whatsapp": com_whatsapp,
        "com_telefone": com_telefone,
        "com_site": com_site,
        "por_regiao": por_regiao,
    }


async def executar_varredura(
    regioes: List[str],
    max_lojas: int,
    output_dir: Path,
    headless: bool = True,
    progress_cb: ProgressCallback = None,
    permitir_repetidas: bool = False,
) -> Dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs_root = output_dir.parent
    historico_lojas, historico_chaves = carregar_historico(outputs_root)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    data_arquivo = datetime.now().strftime("%d-%m-%Y")
    nome_base = f"Varredura-Leads {data_arquivo}"
    log_path = output_dir / f"erros_{timestamp}.log"
    csv_path = output_dir / f"{nome_base}.csv"
    excel_path = output_dir / f"{nome_base}.xlsx"

    total_cidades = len(regioes)
    if progress_cb:
        modo = "permitindo repetidas" if permitir_repetidas else "evitando repetidas"
        engine_nome = "Hyper-Turbo HTTP (Direto)" if headless else "Navegador Visual (Playwright)"
        progress_cb({
            "type": "total",
            "total": total_cidades,
            "message": f"Iniciando motor {engine_nome} em {total_cidades} cidades ({modo})..."
        })

    cidades_fila = list(regioes)
    cidades_processadas = 0
    leads_encontrados: List[Dict] = []
    duplicadas_ignoradas = 0
    lock = asyncio.Lock()

    if headless:
        # MOTOR HYPER-TURBO HTTP (DIRETO ASSÍNCRONO - SEM NAVEGADOR)
        MAX_CONCURRENT_HTTP = 15
        num_workers = min(MAX_CONCURRENT_HTTP, max(1, len(regioes)))

        limits = httpx.Limits(max_keepalive_connections=25, max_connections=35)
        async with httpx.AsyncClient(
            headers=HTTP_HEADERS, follow_redirects=True, timeout=18.0, limits=limits
        ) as client:

            async def worker_http():
                nonlocal cidades_processadas, duplicadas_ignoradas
                while True:
                    async with lock:
                        if not cidades_fila:
                            break
                        cidade_atual = cidades_fila.pop(0)

                    lojas_cidade = await coletar_lojas_cidade_http(
                        client, cidade_atual, max_lojas, log_path
                    )

                    async with lock:
                        cidades_processadas += 1
                        novas_lojas = []
                        for loja in lojas_cidade:
                            chaves = chaves_loja(loja)
                            if not permitir_repetidas and chaves.intersection(historico_chaves):
                                duplicadas_ignoradas += 1
                                continue
                            novas_lojas.append(loja)
                            historico_chaves.update(chaves)

                        leads_encontrados.extend(novas_lojas)

                        if progress_cb:
                            msg = f"Cidades: {cidades_processadas}/{total_cidades} ({len(leads_encontrados)} novos leads)"
                            progress_cb({
                                "type": "item_done",
                                "current": cidades_processadas,
                                "total": total_cidades,
                                "message": msg,
                            })

                        # Checkpoint incremental a cada 20 cidades ou ao finalizar
                        if cidades_processadas % 20 == 0 or cidades_processadas == total_cidades:
                            if leads_encontrados:
                                unicos_atuais = tratar_resultados(leads_encontrados)
                                salvar_csv(unicos_atuais, csv_path)
                                salvar_excel(unicos_atuais, excel_path)

                    await asyncio.sleep(0.04)

            tasks = [worker_http() for _ in range(num_workers)]
            await asyncio.gather(*tasks)

    else:
        # MODO VISUAL (NAVEGADOR CHROMIUM ABERTO NA TELA)
        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--blink-settings=imagesEnabled=false",
            "--disable-extensions",
            "--disable-background-networking",
        ]

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, args=browser_args)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768},
                locale="pt-BR",
            )

            # Injetar camuflagem stealth contra bloqueios do Google
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
            """)

            # Bloquear imagens, vídeos e fontes web
            async def bloquear_midia(route):
                if route.request.resource_type in ["image", "media", "font"]:
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", bloquear_midia)

            # Tratar aceite de cookies caso o Google Maps exiba tela inicial
            page_init = await context.new_page()
            try:
                await page_init.goto("https://www.google.com/maps", wait_until="domcontentloaded", timeout=20000)
                try:
                    botao = page_init.locator('button:has-text("Aceitar tudo"), button:has-text("Reject all"), button:has-text("Rejeitar tudo")')
                    if await botao.count() > 0:
                        await botao.first.click()
                except Exception:
                    pass
            except Exception:
                pass
            finally:
                await page_init.close()

            # Concorrência otimizada de 3 abas paralelas
            MAX_CONCURRENT_CITIES = 3

            async def worker_cidade():
                nonlocal cidades_processadas, duplicadas_ignoradas
                page = await context.new_page()
                try:
                    while True:
                        async with lock:
                            if not cidades_fila:
                                break
                            cidade_atual = cidades_fila.pop(0)

                        lojas_cidade = await coletar_lojas_cidade(page, cidade_atual, max_lojas, log_path)

                        async with lock:
                            cidades_processadas += 1
                            novas_lojas = []
                            for loja in lojas_cidade:
                                chaves = chaves_loja(loja)
                                if not permitir_repetidas and chaves.intersection(historico_chaves):
                                    duplicadas_ignoradas += 1
                                    continue
                                novas_lojas.append(loja)
                                historico_chaves.update(chaves)

                            leads_encontrados.extend(novas_lojas)

                            if progress_cb:
                                msg = f"Cidades: {cidades_processadas}/{total_cidades} ({len(leads_encontrados)} novos leads)"
                                progress_cb({
                                    "type": "item_done",
                                    "current": cidades_processadas,
                                    "total": total_cidades,
                                    "message": msg,
                                })

                            # Checkpoint incremental a cada 15 cidades ou ao finalizar
                            if cidades_processadas % 15 == 0 or cidades_processadas == total_cidades:
                                if leads_encontrados:
                                    unicos_atuais = tratar_resultados(leads_encontrados)
                                    salvar_csv(unicos_atuais, csv_path)
                                    salvar_excel(unicos_atuais, excel_path)
                finally:
                    await page.close()

            num_workers = min(MAX_CONCURRENT_CITIES, max(1, len(regioes)))
            tasks = [worker_cidade() for _ in range(num_workers)]
            await asyncio.gather(*tasks)

            await context.close()
            await browser.close()

    unicos = tratar_resultados(leads_encontrados)
    if permitir_repetidas:
        novos = unicos
        lojas_para_historico, _ = filtrar_lojas_novas(unicos, historico_chaves)
    else:
        novos = unicos
        lojas_para_historico = novos

    historico_atualizado = historico_lojas + lojas_para_historico

    salvar_csv(novos, csv_path)
    salvar_excel(novos, excel_path)
    salvar_historico(outputs_root, historico_atualizado)
    resumo = montar_resumo(novos, regioes)

    return {
        "dados": novos,
        "resumo": resumo,
        "csv_path": str(csv_path),
        "excel_path": str(excel_path),
        "log_path": str(log_path) if log_path.exists() else "",
        "duplicadas_ignoradas": duplicadas_ignoradas,
        "repetidas_permitidas": permitir_repetidas,
        "historico_total": len(historico_atualizado),
    }
