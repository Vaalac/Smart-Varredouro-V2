# 🎯 Varredouro de Leads - Cobertura Nacional

Plataforma inteligente de prospecção comercial B2B para o Google Maps em alta velocidade, cobrindo todos os **5.571 municípios do Brasil** (27 UFs) com geração automática de planilhas Excel (.xlsx) e CSV com links diretos de WhatsApp e Lead Scoring.

---

## ⚡ Diferenciais & Recursos

- 🚀 **Motor Hyper-Turbo HTTP:** Extração assíncrona direta sem navegador, varrendo capitais em segundos e o país inteiro em minutos.
- 📱 **WhatsApp Direto:** Identificação automática de celulares e geração de links diretos `wa.me/55...`.
- 🔥 **Lead Scoring:** Qualificação inteligente de leads quentes, mornos e frios com base em nota, reviews e presença digital.
- 📊 **Excel & CSV Prontos:** Autoajuste de colunas, cabeçalhos estilizados e links clicáveis.
- 🛡️ **Conformidade LGPD:** Enquadramento legal para dados públicos comerciais B2B (Art. 7º, § 4º da LGPD).
- 🌓 **Temas Claro e Escuro:** Interface moderna e responsiva com alternância de tema.

---

## 🚀 Como Rodar o Projeto

### 1. Clonar o repositório
```bash
git clone https://github.com/Vaalac/Varredouro-Smart-Trigo.git
cd Varredouro-Smart-Trigo
```

### 2. Criar e ativar o ambiente virtual
```bash
python -m venv .venv
```

* **No Windows:**
```bash
.venv\Scripts\activate
```

* **No Linux / Mac:**
```bash
source .venv/bin/activate
```

### 3. Instalar as dependências
```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Iniciar o servidor
```bash
uvicorn app:app --reload
```
*(No Windows, você também pode simplesmente dar dois cliques no `run.bat`)*

Acesse no navegador:
👉 **http://127.0.0.1:8000**

---

## 📋 Como Usar

1. **Escolha o Escopo:**
   - **`📍 Escolher Cidades`**: Digite o nome de qualquer cidade na busca rápida ou escolha pelo estado (inclui opção *Brasil Inteiro - 5.571 cidades*).
   - **`🏛️ 27 Capitais Mais Requisitadas`**: Varredura ultra-rápida nos 27 maiores polos econômicos do país.
2. **Defina a Quantidade de Lojas por Cidade:**
   - Selecione entre `3 lojas`, `5 lojas`, `10 lojas`, `20 lojas` ou digite um limite customizado.
3. **Inicie a Varredura:**
   - Acompanhe a barra de progresso ao vivo na tela de status.
   - Ao finalizar, baixe a planilha completa em **Excel (.xlsx)** ou **CSV**.

---

## ⚖️ Conformidade e Aviso Legal

Esta ferramenta extrai unicamente dados de contato comercial de pessoas jurídicas disponibilizados de forma pública pelas próprias empresas no Google Maps, amparada pelo **Artigo 7º, § 4º da Lei nº 13.709/2018 (LGPD)** e pelo legítimo interesse para relações comerciais B2B. A abordagem e utilização dos contatos é de exclusiva responsabilidade do operador.
