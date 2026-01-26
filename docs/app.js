function brl(v){ return (v||0).toLocaleString("pt-BR",{style:"currency",currency:"BRL"}); }

async function load() {
  const [deps, meta] = await Promise.all([
    fetch("./data/deputados.json").then(r=>r.json()),
    fetch("./data/metadata.json").then(r=>r.json()).catch(()=>null),
  ]);

  if (meta) {
    document.getElementById("meta").textContent =
      `Última atualização: ${meta.updated_at} · Ano: ${meta.ano} · Legislatura: ${meta.id_legislatura}`;
  } else {
    document.getElementById("meta").textContent = "";
  }

  // preencher filtros
  const ufs = [...new Set(deps.map(d=>d.uf).filter(Boolean))].sort();
  const partidos = [...new Set(deps.map(d=>d.partido).filter(Boolean))].sort();

  const ufSel = document.getElementById("uf");
  const pSel = document.getElementById("partido");
  ufs.forEach(uf=>{ const o=document.createElement("option"); o.value=uf; o.textContent=uf; ufSel.appendChild(o); });
  partidos.forEach(p=>{ const o=document.createElement("option"); o.value=p; o.textContent=p; pSel.appendChild(o); });

  // ordenar por gasto ano
  deps.sort((a,b)=> (b.gasto_ano||0)-(a.gasto_ano||0));

  function render() {
    const q = (document.getElementById("q").value || "").toLowerCase().trim();
    const uf = ufSel.value;
    const partido = pSel.value;

    const filtered = deps.filter(d => {
      if (uf && d.uf !== uf) return false;
      if (partido && d.partido !== partido) return false;
      if (q && !(d.nome.toLowerCase().includes(q) || (d.nomeCivil||"").toLowerCase().includes(q))) return false;
      return true;
    });

    const list = document.getElementById("list");
    list.innerHTML = "";
    filtered.forEach(d => {
      const el = document.createElement("div");
      el.className = "card";
      el.innerHTML = `
        <div class="cardTop">
          <img class="avatar" src="${d.foto || ""}" alt="Foto" />
          <div>
            <strong>${d.nome}</strong><br/>
            <span class="sub">${d.partido || ""} · ${d.uf || ""}</span>
          </div>
        </div>
        <div class="kpis">
          <span><b>Ano:</b> ${brl(d.gasto_ano)}</span>
          <span><b>Mês:</b> ${brl(d.gasto_mes)}</span>
        </div>
        <div>
          <a href="./deputado.html?id=${d.id}">Ver detalhes →</a>
        </div>
      `;
      list.appendChild(el);
    });
  }

  document.getElementById("q").addEventListener("input", render);
  ufSel.addEventListener("change", render);
  pSel.addEventListener("change", render);
  render();
}

load().catch(err=>{
  console.error(err);
  document.getElementById("meta").textContent = "Erro ao carregar dados. Confira se a pasta docs/data existe.";
});
