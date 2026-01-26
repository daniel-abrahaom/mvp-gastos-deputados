import json
import os
import zipfile
from io import BytesIO
from datetime import datetime, timezone, date
import urllib.request
import urllib.error

API_BASE = "https://dadosabertos.camara.leg.br/api/v2"

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (GitHubActions) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
}

def http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)

def download_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read()

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def pick_current_legislatura() -> int:
 # Pega legislaturas pela API oficial v2 (mais estável)
    url = f"{API_BASE}/legislaturas?itens=200&ordem=DESC&ordenarPor=id"
    data = http_get_json(url)
    hoje = date.today()

    legs = data.get("dados", [])
    for leg in legs:
        di = leg.get("dataInicio")
        df = leg.get("dataFim")
        leg_id = leg.get("id")
        if not di or not df or leg_id is None:
            continue

        try:
            di_d = date.fromisoformat(di)
            df_d = date.fromisoformat(df)
        except:
            continue

        if di_d <= hoje <= df_d:
            return int(leg_id)

    # fallback: maior id disponível
    ids = [int(l.get("id")) for l in legs if l.get("id") is not None]
    return max(ids) if ids else 0

def fetch_deputados_em_exercicio(id_leg: int) -> list:
    url = f"{API_BASE}/deputados?idLegislatura={id_leg}&itens=1000&ordem=ASC&ordenarPor=nome"
    data = http_get_json(url)
    return data.get("dados", [])

def fetch_cota_ano_json(ano: int) -> list:
    zip_url = f"https://www.camara.leg.br/cotas/Ano-{ano}.json.zip"

    b = download_bytes(zip_url)

    if len(b) < 4 or b[:2] != b"PK":
        snippet = b[:200].decode("utf-8", errors="replace")
        raise RuntimeError(
            "Download da cota NÃO retornou ZIP. Início da resposta:\n" + snippet
        )

    z = zipfile.ZipFile(BytesIO(b))
    json_files = [n for n in z.namelist() if n.lower().endswith(".json")]

    if not json_files:
        raise RuntimeError("ZIP da cota não contém arquivo .json.")

    raw = z.read(json_files[0]).decode("utf-8", errors="replace")
    parsed = json.loads(raw)

    # Caso 1: {"dados": [...]}
    if isinstance(parsed, dict) and "dados" in parsed:
        return parsed["dados"]

    # Caso 2: lista direta
    if isinstance(parsed, list):
        # lista de strings JSON
        if parsed and isinstance(parsed[0], str):
            out = []
            for s in parsed:
                if not isinstance(s, str):
                    continue
                s = s.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                    if isinstance(obj, dict):
                        out.append(obj)
                except:
                    continue
            return out

        return parsed

    raise RuntimeError("Formato inesperado no JSON da cota.")

def main():
    out_base = os.path.join("docs", "data")
    detalhes_dir = os.path.join(out_base, "detalhes")
    ensure_dir(out_base)
    ensure_dir(detalhes_dir)

    ano = date.today().year
    mes_atual = f"{date.today().month:02d}"

    id_leg = pick_current_legislatura()
    if not id_leg:
        raise RuntimeError("Não consegui identificar a legislatura atual.")

    deputados = fetch_deputados_em_exercicio(id_leg)
    dep_map = {int(d["id"]): d for d in deputados if "id" in d}

    despesas = fetch_cota_ano_json(ano)

def get_dep_id(item):
    if not isinstance(item, dict):
        return None

    for k in ("idDeputado", "ideCadastro"):
        v = item.get(k)
        if v is None:
            continue
        try:
            return int(v)
        except:
            continue
    return None


    agg = {}
    for item in despesas:
        dep_id = get_dep_id(item)
        if dep_id is None or dep_id not in dep_map:
            continue

        valor = item.get("valorLiquido") or item.get("valorDocumento") or item.get("valor") or 0
        try:
            valor = float(str(valor).replace(",", "."))
        except:
            valor = 0.0

        data_doc = item.get("dataDocumento") or item.get("data") or ""
        mes = ""
        if isinstance(data_doc, str) and len(data_doc) >= 7:
            mes = data_doc[5:7]  # YYYY-MM-DD

        categoria = item.get("tipoDespesa") or item.get("descricao") or "Sem categoria"
        fornecedor = item.get("nomeFornecedor") or item.get("fornecedor") or ""
        doc_url = item.get("urlDocumento") or ""

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
            "valor": round(valor, 2),
            "documento_url": doc_url
        })

    deputados_out = []
    for dep_id, d in dep_map.items():
        info = agg.get(dep_id, {"gasto_ano":0.0,"por_mes":{},"por_categoria":{},"por_fornecedor":{},"lancamentos":[]})
        gasto_mes = float(info["por_mes"].get(mes_atual, 0.0))

        deputados_out.append({
            "id": dep_id,
            "nome": d.get("nome", ""),
            "nomeCivil": d.get("nomeCivil", ""),
            "partido": d.get("siglaPartido", ""),
            "uf": d.get("siglaUf", ""),
            "foto": d.get("urlFoto", ""),
            "gasto_ano": round(float(info["gasto_ano"]), 2),
            "gasto_mes": round(gasto_mes, 2),
        })

        # detalhe por deputado
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
        with open(os.path.join(detalhes_dir, f"{dep_id}.json"), "w", encoding="utf-8") as f:
            json.dump(detail_payload, f, ensure_ascii=False)

    with open(os.path.join(out_base, "deputados.json"), "w", encoding="utf-8") as f:
        json.dump(deputados_out, f, ensure_ascii=False)

    meta = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "ano": ano,
        "id_legislatura": id_leg,
        "sources": [
            "https://dadosabertos.camara.leg.br/",
            "https://dadosabertos.camara.leg.br/swagger/api.html",
            f"https://www.camara.leg.br/cotas/Ano-{ano}.json.zip"
        ]
    }
    with open(os.path.join(out_base, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    print("OK: dados atualizados.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERRO:", str(e))
        raise
