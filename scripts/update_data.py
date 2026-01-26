import json
import os
import sys
import zipfile
from io import BytesIO
from datetime import datetime, timezone, date

import urllib.request

API_BASE = "https://dadosabertos.camara.leg.br/api/v2"

def http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))

def download_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def pick_current_legislatura() -> int:
    # Usa o arquivo oficial de legislaturas (atualização diária)
    # Link descrito na documentação do Dados Abertos
    leg_url = "http://dadosabertos.camara.leg.br/arquivos/legislaturas/json/legislaturas.json"
    data = http_get_json(leg_url)
    hoje = date.today()

    # estrutura típica: {"dados":[{"id":..., "dataInicio":"YYYY-MM-DD", "dataFim":"YYYY-MM-DD", ...}], ...}
    legs = data.get("dados", [])
    for leg in legs:
        di = leg.get("dataInicio")
        df = leg.get("dataFim")
        if not di or not df:
            continue
        di_d = date.fromisoformat(di)
        df_d = date.fromisoformat(df)
        if di_d <= hoje <= df_d:
            return int(leg["id"])

    # fallback: pega a maior id (mais recente)
    ids = [int(l["id"]) for l in legs if "id" in l]
    return max(ids) if ids else 0

def fetch_deputados_em_exercicio(id_leg: int) -> list:
    # Endpoint de deputados (API v2), filtrando por legislatura e em exercício
    url = f"{API_BASE}/deputados?idLegislatura={id_leg}&itens=1000&ordem=ASC&ordenarPor=nome"
    data = http_get_json(url)
    return data.get("dados", [])

def fetch_cota_ano_json(ano: int) -> list:
    # Documentação: http://www.camara.leg.br/cotas/Ano-{ano}.json.zip
    # (descrita na página do Swagger do Dados Abertos)
    zip_url = f"http://www.camara.leg.br/cotas/Ano-{ano}.json.zip"
    b = download_bytes(zip_url)
    z = zipfile.ZipFile(BytesIO(b))
    # dentro do zip geralmente há um .json
    json_name = [n for n in z.namelist() if n.lower().endswith(".json")][0]
    raw = z.read(json_name).decode("utf-8")
    # o JSON costuma ser uma lista de objetos
    return json.loads(raw)

def main():
    # onde o site lê os dados
    out_base = os.path.join("docs", "data")
    detalhes_dir = os.path.join(out_base, "detalhes")
    ensure_dir(out_base)
    ensure_dir(detalhes_dir)

    ano = date.today().year
    id_leg = pick_current_legislatura()

    deputados = fetch_deputados_em_exercicio(id_leg)
    # cria um map por id
    dep_map = {int(d["id"]): d for d in deputados}

    # baixa todas as despesas do ano (um arquivo oficial só)
    despesas = fetch_cota_ano_json(ano)

    # campos variam; vamos tratar os mais comuns e ser tolerante
    # idea: identificar o deputado pelo id (quando disponível) ou pelo nome parlamentar
    # muitos registros trazem "ideCadastro" (id antigo) e/ou "idDeputado" dependendo do ano
    # vamos tentar os campos mais prováveis:
    def get_dep_id(item):
        for k in ("idDeputado", "id_deputado", "ideCadastro", "ideCadastroDeputado"):
            if k in item and str(item[k]).isdigit():
                return int(item[k])
        return None

    # agregações por deputado
    agg = {}
    for item in despesas:
        dep_id = get_dep_id(item)
        if dep_id is None:
            continue

        # só considera deputados que estão na lista atual (em exercício)
        if dep_id not in dep_map:
            continue

        # valor
        valor = item.get("valorLiquido") or item.get("valorDocumento") or item.get("valor") or 0
        try:
            valor = float(str(valor).replace(",", "."))
        except:
            valor = 0.0

        data_doc = item.get("dataDocumento") or item.get("data") or ""
        mes = ""
        try:
            if data_doc:
                mes = str(data_doc)[5:7]  # YYYY-MM-DD
        except:
            mes = ""

        categoria = item.get("tipoDespesa") or item.get("descricao") or "Sem categoria"
        fornecedor = item.get("nomeFornecedor") or item.get("fornecedor") or ""
        doc_url = item.get("urlDocumento") or item.get("documentoUrl") or ""

        a = agg.setdefault(dep_id, {
            "gasto_ano": 0.0,
            "por_mes": {},
            "por_categoria": {},
            "por_fornecedor": {},
            "lancamentos": []
        })

        a["gasto_ano"] += valor
        if mes:
            a["por_mes"][mes] = a["por_mes"].get(mes, 0.0) + valor
        a["por_categoria"][categoria] = a["por_categoria"].get(categoria, 0.0) + valor
        if fornecedor:
            a["por_fornecedor"][fornecedor] = a["por_fornecedor"].get(fornecedor, 0.0) + valor

        a["lancamentos"].append({
            "data": data_doc,
            "categoria": categoria,
            "fornecedor": fornecedor,
            "valor": valor,
            "documento_url": doc_url
        })

    # calcula gasto do mês atual
    mes_atual = f"{date.today().month:02d}"

    deputados_out = []
    for dep_id, d in dep_map.items():
        info = agg.get(dep_id, {"gasto_ano":0.0,"por_mes":{},"por_categoria":{},"por_fornecedor":{},"lancamentos":[]})
        gasto_mes = float(info["por_mes"].get(mes_atual, 0.0))
        deputados_out.append({
            "id": dep_id,
            "nome": d.get("nome", ""),
            "nomeCivil": d.get("nomeCivil", ""),
            "siglaPartido": d.get("siglaPartido", ""),
            "partido": d.get("siglaPartido", ""),
            "uf": d.get("siglaUf", ""),
            "foto": d.get("urlFoto", ""),
            "gasto_ano": round(float(info["gasto_ano"]), 2),
            "gasto_mes": round(gasto_mes, 2),
        })

        # grava detalhe por deputado (um arquivo por deputado — ainda é leve)
        detalhe_path = os.path.join(detalhes_dir, f"{dep_id}.json")
        # ordena lançamentos por data desc (quando der)
        try:
            info["lancamentos"].sort(key=lambda x: x.get("data",""), reverse=True)
        except:
            pass
        detail_payload = {
            "id": dep_id,
            "ano": ano,
            "mes_atual": mes_atual,
            "gasto_ano": round(float(info["gasto_ano"]), 2),
            "gasto_mes": round(gasto_mes, 2),
            "por_mes": {k: round(v,2) for k,v in info["por_mes"].items()},
            "por_categoria": {k: round(v,2) for k,v in info["por_categoria"].items()},
            "por_fornecedor": {k: round(v,2) for k,v in info["por_fornecedor"].items()},
            "lancamentos": info["lancamentos"]
        }
        with open(detalhe_path, "w", encoding="utf-8") as f:
            json.dump(detail_payload, f, ensure_ascii=False)

    # salva deputados.json
    with open(os.path.join(out_base, "deputados.json"), "w", encoding="utf-8") as f:
        json.dump(deputados_out, f, ensure_ascii=False)

    # metadata
    meta = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "ano": ano,
        "id_legislatura": id_leg,
        "sources": [
            "https://dadosabertos.camara.leg.br/",
            "https://dadosabertos.camara.leg.br/swagger/api.html",
            f"http://www.camara.leg.br/cotas/Ano-{ano}.json.zip"
        ]
    }
    with open(os.path.join(out_base, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    print("OK: dados atualizados.")

if __name__ == "__main__":
    main()
