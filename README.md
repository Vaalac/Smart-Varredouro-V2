# 🏠 Varredouro de Imóveis & Imobiliárias - Cobertura Nacional

Plataforma inteligente de prospecção comercial B2B especializada no **setor imobiliário** (imobiliárias, corretores, locação, administradoras, loteadoras e incorporadoras), cobrindo todos os **5.571 municípios do Brasil** (27 UFs) com geração automática de planilhas Excel (.xlsx) e CSV com links diretos de WhatsApp, CNPJ, e-mails e Lead Scoring.

---

## ⚡ Diferenciais & Recursos

- 🏛️ **Motor Base CNPJ Oficial (Zero Bloqueio):** Consulta direta e ultrarrápida aos dados abertos da Receita Federal (atualizado 2026) via DuckDB. Zero CAPTCHA, zero banimento de IP e dados 100% enriquecidos com Razão Social, CNPJ ativo, E-mail oficial e Telefones.
- 🎯 **Segmentação Imobiliária por CNAE:**
  - Todas as Imobiliárias & Corretores (6821-8/01, 6821-8/02, 6810-2/02, etc.)
  - Corretagem, Venda & Avaliação de Imóveis (6821-8/01)
  - Locação & Administração de Bens Imóveis (6821-8/02, 6810-2/02)
  - Loteadoras, Incorporadoras & Compra/Venda (4110-7/00, 6810-2/01)
  - CNAE Personalizado
- 🚀 **Motor Alternativo Google Maps HTTP:** Extração complementar assíncrona direta sem navegador.
- 📱 **WhatsApp Direto:** Identificação automática de celulares e geração de links diretos `wa.me/55...`.
- 🔥 **Lead Scoring:** Qualificação inteligente de leads quentes, mornos e frios com base em contato direto, presença digital e avaliações.
- 📊 **Excel & CSV Prontos:** Autoajuste de colunas, cabeçalhos estilizados e links clicáveis para e-mails e WhatsApp.
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

1. **Escolha o Motor & Nicho:**
   - **`🏛️ Base CNPJ Oficial (Recomendado)`**: Sem limites ou bloqueios, puxa CNPJ, e-mail e dados cadastrais da Receita.
   - **`⚡ Google Maps`**: Motor secundário com scraping web.
   - Escolha o nicho imobiliário desejado (Todas as Imobiliárias, Venda, Locação, etc.).
2. **Escolha o Escopo Geográfico:**
   - **`📍 Escolher Cidades`**: Digite o nome de qualquer cidade na busca rápida ou escolha pelo estado (inclui opção *Brasil Inteiro - 5.571 cidades*).
   - **`🏛️ 27 Capitais Mais Requisitadas`**: Varredura ultra-rápida nos 27 maiores polos econômicos do país.
3. **Defina a Quantidade de Leads por Cidade:**
   - Selecione entre `3 leads`, `5 leads`, `10 leads`, `20 leads` ou digite um limite customizado.
4. **Inicie a Varredura:**
   - Acompanhe a barra de progresso ao vivo na tela de status.
   - Ao finalizar, baixe a planilha completa em **Excel (.xlsx)** ou **CSV**.

---

## ⚖️ Conformidade e Aviso Legal

Esta ferramenta extrai unicamente dados cadastrais públicos de pessoas jurídicas (Receita Federal e perfis públicos no Google Maps), amparada pelo **Artigo 7º, § 4º da Lei nº 13.709/2018 (LGPD)** e pelo legítimo interesse para relações comerciais B2B. A abordagem e utilização dos contatos é de exclusiva responsabilidade do operador.
