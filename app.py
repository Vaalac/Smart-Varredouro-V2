import asyncio
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from municipios_br import (
    ESTADOS,
    MUNICIPIOS_LISTA,
    REGIOES_DISPONIVEIS,
    canonizar_regiao,
    obter_capitais,
    obter_cidades_uf,
    validar_regiao,
)
from scraper import executar_varredura

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BASE_DIR / ".playwright-browsers"))

app = FastAPI(title="Varredouro de Leads")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

jobs: Dict[str, Dict] = {}


def executar_async(coro):
    if sys.platform.startswith("win"):
        loop = asyncio.ProactorEventLoop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    return asyncio.run(coro)


def atualizar_job(job_id: str, patch: Dict) -> None:
    jobs[job_id].update(patch)
    jobs[job_id]["updated_at"] = datetime.now().isoformat(timespec="seconds")


def progress_factory(job_id: str):
    def progress(event: Dict) -> None:
        job = jobs[job_id]
        if event.get("type") == "message":
            atualizar_job(job_id, {"message": event.get("message", "")})
        elif event.get("type") == "total":
            atualizar_job(
                job_id,
                {
                    "total": event.get("total", 0),
                    "message": event.get("message", ""),
                },
            )
        elif event.get("type") == "item_done":
            atual = event.get("current", job.get("processed", 0) + 1)
            total = max(1, event.get("total", job.get("total", 1)))
            atualizar_job(
                job_id,
                {
                    "processed": atual,
                    "progress": min(100, round((atual / total) * 100)),
                    "message": event.get("message", f"Processando: {atual}/{total}"),
                },
            )

    return progress


def executar_job(job_id: str, regioes: List[str], max_lojas: int, abrir_navegador: bool, permitir_repetidas: bool) -> None:
    try:
        atualizar_job(job_id, {"status": "running", "message": "Iniciando varredura ultra-rápida..."})
        job_dir = OUTPUTS_DIR / job_id
        resultado = executar_async(
            executar_varredura(
                regioes=regioes,
                max_lojas=max_lojas,
                output_dir=job_dir,
                headless=not abrir_navegador,
                progress_cb=progress_factory(job_id),
                permitir_repetidas=permitir_repetidas,
            )
        )

        resumo = resultado["resumo"]
        duplicadas = resultado.get("duplicadas_ignoradas", 0)
        historico_total = resultado.get("historico_total", resumo["total"])
        mensagem_final = "Varredura finalizada. Baixe o Excel ou CSV abaixo."
        if resultado.get("repetidas_permitidas"):
            mensagem_final = f"Varredura finalizada incluindo lojas repetidas. {duplicadas} lojas do resultado já estavam no histórico."
        elif duplicadas:
            mensagem_final = f"Varredura finalizada. {duplicadas} lojas repetidas foram ignoradas. Baixe os novos leads abaixo."
        atualizar_job(
            job_id,
            {
                "status": "done",
                "progress": 100,
                "processed": resumo["total"],
                "message": mensagem_final,
                "summary": resumo,
                "excel_path": resultado["excel_path"],
                "csv_path": resultado["csv_path"],
                "log_path": resultado.get("log_path", ""),
                "duplicadas_ignoradas": duplicadas,
                "repetidas_permitidas": resultado.get("repetidas_permitidas", False),
                "historico_total": historico_total,
            },
        )
    except Exception as e:
        detalhe = str(e).strip() or repr(e)
        atualizar_job(
            job_id,
            {
                "status": "error",
                "message": f"Erro na execução: {detalhe}",
            },
        )


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "estados": ESTADOS,
            "capitais": obter_capitais(),
            "total_cidades": len(MUNICIPIOS_LISTA),
            "regioes": ESTADOS["SP"]["cidades"],
        },
    )


@app.get("/api/estados")
def listar_estados():
    resumo = [
        {
            "uf": uf,
            "nome": dados["nome"],
            "total_cidades": len(dados["cidades"]),
        }
        for uf, dados in sorted(ESTADOS.items())
    ]
    return JSONResponse(resumo)


@app.get("/api/cidades/{uf}")
def listar_cidades_uf(uf: str):
    cidades = obter_cidades_uf(uf)
    if not cidades:
        return JSONResponse({"error": f"Estado '{uf}' não encontrado"}, status_code=404)
    return JSONResponse({"uf": uf.upper(), "cidades": cidades})


@app.get("/api/capitais")
def listar_capitais():
    return JSONResponse({"capitais": obter_capitais()})


@app.post("/executar")
def executar(
    background_tasks: BackgroundTasks,
    regioes: List[str] = Form(...),
    max_lojas: int = Form(20),
    abrir_navegador: bool = Form(False),
    permitir_repetidas: bool = Form(False),
):
    if any(r in ("__TODAS__", "BRASIL_INTEIRO", "TODAS") for r in regioes):
        regioes_validas = list(MUNICIPIOS_LISTA)
    else:
        regioes_validas = [canonizar_regiao(r) for r in regioes if r.strip() and validar_regiao(r)]
        if not regioes_validas:
            regioes_validas = [r.strip() for r in regioes if r.strip()]

    if not regioes_validas:
        regioes_validas = ["São Paulo, SP"]

    max_lojas = max(1, min(int(max_lojas), 100))
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "progress": 0,
        "processed": 0,
        "total": 0,
        "message": "Na fila para execução ultra-rápida...",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "regioes": regioes_validas,
        "max_lojas": max_lojas,
        "permitir_repetidas": permitir_repetidas,
    }

    background_tasks.add_task(executar_job, job_id, regioes_validas, max_lojas, abrir_navegador, permitir_repetidas)
    return RedirectResponse(url=f"/status/{job_id}", status_code=303)


@app.get("/status/{job_id}", response_class=HTMLResponse)
def status_page(request: Request, job_id: str):
    job = jobs.get(job_id)
    if not job:
        return templates.TemplateResponse("not_found.html", {"request": request}, status_code=404)
    return templates.TemplateResponse("status.html", {"request": request, "job": job})


@app.get("/api/jobs/{job_id}")
def status_api(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job não encontrado"}, status_code=404)
    return dict(job)


def arquivo_do_job(job_id: str, tipo: str) -> Path:
    job = jobs.get(job_id)
    if not job:
        raise FileNotFoundError("Job não encontrado")
    key = "excel_path" if tipo == "excel" else "csv_path"
    path = Path(job.get(key, ""))
    if not path.exists():
        raise FileNotFoundError("Arquivo não encontrado")
    return path


@app.get("/download/{job_id}/{tipo}")
def download(job_id: str, tipo: str):
    if tipo not in {"excel", "csv"}:
        return JSONResponse({"error": "Tipo inválido"}, status_code=400)
    try:
        path = arquivo_do_job(job_id, tipo)
        return FileResponse(path, filename=path.name)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
