function brl(v){ return (v||0).toLocaleString("pt-BR",{style:"currency",currency:"BRL"}); }
function getId(){ return new URLSearchParams(location.search).get("id"); }

async function load() {
  const id = getId();
  if (!id) { document.getElementById("perfil").textContent="ID não informado."; return; }

  const meta = await fetch("./data/metadata.json").then(r=>r.json()).catch(()=>null);
  if (meta) {
    document.getElementById("meta").textContent =
      `Última atualização: ${meta.updated_at} · Ano: ${meta.ano} · Legislatura: ${meta.id_legislatura}`;
  }

  const deps = await fetch("./data/deputados.json").then(r=>r.json());
  const d = deps.find(x => String(x.id) === String(id));
  if (!d) { document.getElementById("perfil").textContent="Deputado não encontrado."; return; }

  document.title = `${d.nome} — Gastos (MVP)`;

  document.getElementById("perfil").innerHTML = `
    <img src="${d.foto || ""}" alt="Foto" />
    <div>
      <h1 style="margin:0">${d.nome}</h1>
      <div class="sub">${d.partido || ""} · ${d.uf || ""}</div>
      <div class="sub">Fonte: Câmara dos Deputados (Dados Abertos / Cota Parlamentar)</div>
    </div>
  `;

  const detalhe = await fetch(`./data/detalhes/${id}.json`).then(r=>r.json());

  const cards = document.getElementById("cards");
  cards.innerHTML = `
    <div class="mini"><div class="label">Gasto no ano</div><div class="value">${brl(detalhe.gasto_ano)}</div></div>
    <div class="mini"><div class="label">Gasto no mês</div><div class="value">${brl(detalhe.gasto_mes)}</div></div>
    <div class="mini"><div class="label">Lançamentos no ano</div><div class="value">${detalhe.lancamentos.length}</div></div>
  `;

  // gráfico por mês
  const meses = Array.from({length:12}, (_,i)=> String(i+1).padStart(2,"0"));
  const serieMes = meses.map(m => detalhe.por_mes[m] || 0);

  new Chart(document.getElementById("chartMes"), {
    type: "bar",
    data: { labels: meses.map(m=>`M${m}`), datasets: [{ label: "R$", data: serieMes }] },
    options: { responsive:true, plugins:{ legend:{ display:false } } }
  });

  // top categorias
  const cats = Object.entries(detalhe.por_categoria).sort((a,b)=>b[1]-a[1]).slice(0,8);
  new Chart(document.getElementById("chartCat"), {
    type: "pie",
    data: { labels: cats.map(c=>c[0]), datasets: [{ data: cats.map(c=>c[1]) }] },
    options: { responsive:true }
  });

  // top fornecedores
  const tops = Object.entries(detalhe.por_fornecedor).sort((a,b)=>b[1]-a[1]).slice(0,10);
  document.getElementById("topFornecedores").innerHTML = `
    <ol>
      ${tops.map(([k,v])=>`<li>${k} — <b>${brl(v)}</b></li>`).join("")}
    </ol>
  `;

  // tabela de lançamentos
  const tb = document.querySelector("#tabela tbody");
  tb.innerHTML = "";
  detalhe.lancamentos.slice(0,400).forEach(l => { // limita no MVP p/ não pesar
    const tr = document.createElement("tr");
    const docLink = l.documento_url ? `<a href="${l.documento_url}" target="_blank" rel="noreferrer">abrir</a>` : "";
    tr.innerHTML = `
      <td>${l.data || ""}</td>
      <td>${l.categoria || ""}</td>
      <td>${l.fornecedor || ""}</td>
      <td class="num">${(l.valor||0).toFixed(2)}</td>
      <td>${docLink}</td>
    `;
    tb.appendChild(tr);
  });
}

load().catch(err=>{
  console.error(err);
  document.getElementById("perfil").textContent = "Erro ao carregar dados do deputado.";
});
