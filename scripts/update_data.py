import json
import os
import zipfile
from io import BytesIO
from datetime import datetime, timezone, date
import urllib.request

API_BASE = "https://dadosabertos.camara.leg.br/api/v2"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (GitHubActions) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
}

def http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=90) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)

def download_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read()

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def pick_current_legislatura() -> int:
    # Preferência: pegar a legislatura que contém a data de hoje
    url = f"{API_BASE}/legislaturas?itens=200&ordem=DESC&ordenarPor=id"
    data = http_get_json(url)
    hoje = date.today()

    legs = data.get("dados", [])
    for leg in legs:
        leg_id = leg.get("id")
        di = leg.get("dataInicio")
        df = leg.get("dataFim")
        if leg_id is None or not di or not df:
            continue
        try:
            di_d = date.fromisoformat(di)
            df_d = date.fromisoformat(df)
        except:
            continue
        if di_d <= hoje <= df_d:
            return int(leg_id)

    # Fallback: maior id disponível
    ids = [int(l.get("id")) for l in legs if l.get("id") is not None]
    return max(ids) if ids else 0

def fetch_deputados_em_exercicio(id_leg: int) -> list:
    # Tentativa 1: com legislatura
    url = f"{API_BASE}/deputados?idLegislatura={id_leg}&itens=1000&ordem=ASC&ordenarPor=nome"
    data = http_get_json(url)
    deps = data.get("dados", [])
    return deps

def fetch_deputados_fallback() -> list:
    # Tentativa 2 (fallback): sem legislatura (algumas vezes funciona melhor)
    url = f"{API_BASE}/deputados?itens=1000&ordem=ASC&ordenarPor=nome"
    data = http_get_json(url)
    return data.get("dados", [])

def fetch_cota_ano_json(ano: int) -> list:
    # Arquivo oficial da Cota Parlamentar (zip com json)
    zip_url = f"https://www.camara.leg.br/cotas/Ano-{ano}.json.zip"
    b = download_bytes(zip_url)

    # valida se veio ZIP
    if len(b) < 4 or b[:2] != b"PK":
        snippet = b[:300].decode("utf-8", errors="replace")
        raise RuntimeError("Download da cota NÃO retornou ZIP. Início:\n" + snippet)

    z = zipfile.ZipFile(BytesIO(b))
    json_files = [n for n in z.namelist() if n.lower().endswith(".json")]
    if not json_files:
        raise RuntimeError("ZIP da cota não contém arquivo .json.")

    raw = z.read(json_files[0]).decode("utf-8", errors="replace")
    parsed = json.loads(raw)

    # formato: {"dados":[...]}
    if isinstance(parsed, dict) and isinstance(parsed.get("dados"), list):
        return parsed["dados"]

    # formato: lista direta
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
    # caminhos de saída (sempre dentro de docs/data)
    out_base = os.path.join("docs", "data")
    detalhes_dir = os.path.join(out_base, "detalhes")
    ensure_dir(out_base)
    ensure_dir(detalhes_dir)

    ano = date.today().year
    mes_atual = f"{date.today().month:02d}"

    # 1) legislatura
    id_leg = pick_current_legislatura()
    print("DEBUG: id_legislatura =", id_leg)

    # 2) deputados
    deputados = []
    if id_leg:
        deputados = fetch_deputados_em_exercicio(id_leg)

    if not deputados:
        print("DEBUG: deputados veio vazio com idLegislatura. Tentando fallback sem idLegislatura...")
        deputados = fetch_deputados_fallback()

    print("DEBUG: deputados retornados =", len(deputados))
    if deputados:
        print("DEBUG: exemplo deputado =", deputados[0])

    # Map por idDeputado (id da API v2)
    dep_map = {}
    for d in deputados:
        try:
            dep_id = int(d.get("id"))
            dep_map[dep_id] = d
        except:
            continue

    if not dep_map:
        raise RuntimeError("Não encontrei nenhum deputado na API. Algo mudou/está indisponível.")

    # 3) despesas cota
    despesas = fetch_cota_ano_json(ano)
    print("DEBUG: despesas retornadas =", len(despesas))
    if despesas:
        print("DEBUG: exemplo despesa =", despesas[0])

    # Na Cota, o identificador mais confiável costuma ser ideCadastro.
    # Porém, a API de deputados usa outro id. Então: vamos mapear "id API" -> "ideCadastro" usando endpoint de detalhes.

    # Para não estourar tempo, vamos buscar detalhes só de quem aparece na lista (max ~513).
    # Endpoint: /deputados/{id}
    ide_por_id_api = {}
    for dep_id in list(dep_map.keys()):
        try:
            det = http_get_json(f"{API_BASE}/deputados/{dep_id}")
            dados = det.get("dados", {})
            ide = dados.get("id")  # às vezes vem igual; mas o que queremos é 'idCadastro' / 'idCadastro' etc.
            # Vamos tentar os campos comuns:
            ideCadastro = dados.get("idCadastro") or dados.get("ideCadastro") or dados.get("idCadastroParlamentar")
            if ideCadastro is not None:
                try:
                    ide_por_id_api[dep_id] = int(ideCadastro)
                except:
                    pass
        except:
            continue

    print("DEBUG: mapeamento ideCadastro por deputado =", len(ide_por_id_api))

    # Inverte: ideCadastro -> id_api
    id_api_por_ide = {ide: dep_id for dep_id, ide in ide_por_id_api.items()}

    def get_id_api_from_despesa(item):
        if not isinstance(item, dict):
            return None
        # Tenta os campos mais comuns na Cota
        for k in ("ideCadastro", "idDeputado"):
            v = item.get(k)
            if v is None:
                continue
            try:
                v_int = int(v)
            except:
                continue

            # Se for ideCadastro, converte para id_api
            if k == "ideCadastro":
                return id_api_por_ide.get(v_int)

            # Se for idDeputado (pode já ser id_api em alguns formatos)
            if k == "idDeputado":
                # se bater direto com dep_map, beleza
                if v_int in dep_map:
                    return v_int
                # às vezes idDeputado também é ideCadastro:
                return id_api_por_ide.get(v_int)
        return None

    agg = {}
    matched = 0

    for item in despesas:
        dep_id_api = get_id_api_from_despesa(item)
        if dep_id_api is None or dep_id_api not in dep_map:
            continue

        matched += 1

        valor = item.get("valorLiquido") or item.get("valorDocumento") or item.get("valor") or 0
        try:
            valor = float(str(valor).replace(",", "."))
        except:
            valor = 0.0

        data_doc = item.get("dataDocumento") or item.get("data") or ""
        mes = ""
        if isinstance(data_doc, str) and len(data_doc) >= 7:
            mes = data_doc[5:7]

        categoria = item.get("tipoDespesa") or item.get("descricao") or "Sem categoria"
        fornecedor = item.get("nomeFornecedor") or item.get("fornecedor") or ""
        doc_url = item.get("urlDocumento") or ""

        a = agg.setdefault(dep_id_api, {
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

    print("DEBUG: despesas casadas com deputados =", matched)

    deputados_out = []
    for dep_id_api, d in dep_map.items():
        info = agg.get(dep_id_api, {"gasto_ano":0.0,"por_mes":{},"por_categoria":{},"por_fornecedor":{},"lancamentos":[]})
        gasto_mes = float(info["por_mes"].get(mes_atual, 0.0))

        deputados_out.append({
            "id": dep_id_api,
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
            "id": dep_id_api,
            "ano": ano,
            "mes_atual": mes_atual,
            "gasto_ano": round(float(info["gasto_ano"]), 2),
            "gasto_mes": round(gasto_mes, 2),
            "por_mes": {k: round(v,2) for k,v in info["por_mes"].items()},
            "por_categoria": {k: round(v,2) for k,v in info["por_categoria"].items()},
            "por_fornecedor": {k: round(v,2) for k,v in info["por_fornecedor"].items()},
            "lancamentos": info["lancamentos"]
        }
        with open(os.path.join(detalhes_dir, f"{dep_id_api}.json"), "w", encoding="utf-8") as f:
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
            f"https://www.camara.leg.br/cotas/Ano-{ano}.json.zip"
        ]
    }
    with open(os.path.join(out_base, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    print("OK: dados atualizados e arquivos gerados em docs/data.")

if __name__ == "__main__":
    main()
