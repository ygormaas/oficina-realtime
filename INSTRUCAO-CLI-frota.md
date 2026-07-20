# Instrução para o Claude CLI — Adicionar bloco "Veículos / Frota" ao painel

## Contexto
Arquivo a editar: **`Resumo Oficina.dc.html`** (Design Component, tema claro MaaS, board fixo
1920×1080 que escala para TV). NÃO alterar o formato 16:9, o auto-scale, o trilho de alertas,
os blocos 01–04 já existentes, nem o drill-down. É uma **adição incremental**.

O DC tem duas partes:
- **Template** (dentro de `<x-dc>…</x-dc>`): markup com estilos inline e holes `{{ … }}`.
- **Logic** (`class Component extends DCLogic`): método `renderVals()` retorna os dados.

Regras do projeto (obrigatórias):
- Somente **estilos inline**; nada de classes CSS novas nem `<style>` (exceto o helmet já existente).
- Cores só via tokens: `var(--maas-petroleo)`, `--maas-verde`, `--maas-verde-escuro`,
  `--maas-laranja`, `--maas-petroleo-45/60/25`, `--surface-card`, `--surface-sunken`,
  `--border-subtle`, `--radius-card-lg`, `--shadow-card`. Laranja = acento pontual.
- Números com `font-variant-numeric:tabular-nums` e peso 800, tracking negativo (padrão do painel).
- Cor de status só quando a regra dispara (não pintar nada de vermelho por decoração).
- Copy em pt-BR, títulos em sentence case, labels/eyebrows em CAIXA ALTA com tracking.

## O que adicionar

### 1) KPI "Veículos" (mobilizados × não mobilizados) — imagem 1
Um cartão-KPI com dois números lado a lado:
- **48** — "Mobilizados"
- **5** — "Não mobilizados"
- Título do cartão: **Veículos** com um ponto/indicador verde (`--maas-verde`) no canto.
Estilo: mesmo padrão dos KPIs compostos do painel (ex.: "Mão de obra"): número grande
(≈52–60px, peso 800), label CAIXA ALTA embaixo, divisória vertical fina (`--border-subtle`)
entre os dois valores. Não é crítico — usar `--maas-petroleo` nos números.

### 2) Bloco "Frota" com dois gráficos de barras — imagem 2
Renomear/expandir o **bloco 03** (hoje "Tipo de serviço") NÃO — em vez disso, adicionar as
duas visualizações abaixo como um novo bloco **"05 · Frota e localização"** OU integrá-las ao
bloco 04, conforme o espaço. Preferência: novo tile dentro da linha 2, mantendo tudo em 16:9
sem rolagem (se faltar espaço, reduzir levemente a altura dos tiles existentes).

**a) Localização dos veículos** (barras horizontais):
- Oficina interna — **41**
- Oficina externa — **14**
Barras na cor `--maas-verde` (padrão das barras do painel), trilho `--surface-sunken`,
valor à direita em peso 800.

**b) Tipo de veículos** (barras empilhadas: mobilizado × não mobilizado):
- Pesada — total **32** (mobilizado + não mobilizado)
- Leve — total **16**
Segmento mobilizado = `--maas-verde` (ou petróleo, seguir legenda); segmento não mobilizado =
`--maas-laranja` (acento). Incluir legenda: ● "Veículo mobilizado" · ● "Veículo não mobilizado".
Valores da imagem: as barras mostram 32 e 16 no segmento principal — usar como total e, se não
houver o detalhamento não-mobilizado por tipo, mostrar só o total com o acento proporcional.

> Observação de dados: os totais das duas fontes divergem (48+5=53 vs 41+14=55 vs 32+16=48).
> São recortes diferentes (status × localização × tipo). Manter cada visual com seus próprios
> números exatamente como nas imagens; NÃO tentar reconciliar.

## Como implementar (passo a passo)

1. **Logic — `renderVals()`**: adicionar os dados e expor por nome:
   ```js
   // Veículos (status)
   const veiculos = { mobilizados: 48, naoMobilizados: 5 };
   // Localização
   const locRaw = [ {k:'Oficina interna', n:41}, {k:'Oficina externa', n:14} ];
   const maxLoc = Math.max(...locRaw.map(x=>x.n));
   const locRows = locRaw.map(x => ({ ...x, pct:(x.n/maxLoc*100)+'%' }));
   // Tipo de veículo (mobilizado × não mobilizado) — ajustar splits se houver dado real
   const tipoVeic = [
     { k:'Pesada', total:32, mob:32, nao:0 },
     { k:'Leve',   total:16, mob:16, nao:0 },
   ];
   const maxTV = Math.max(...tipoVeic.map(x=>x.total));
   const tipoVeicRows = tipoVeic.map(x => ({
     k:x.k, total:x.total,
     mobPct:(x.mob/maxTV*100)+'%', naoPct:(x.nao/maxTV*100)+'%',
   }));
   ```
   Retornar `veiculos, locRows, tipoVeicRows` no objeto do `return`.

2. **Template**: seguir o mesmo padrão de tile já usado no bloco 04
   (`background:var(--surface-card);border:1px solid var(--border-subtle);
   border-radius:var(--radius-card-lg);box-shadow:var(--shadow-card)` para o bloco;
   tiles internos `background:rgba(24,59,72,.035);border-radius:14px`).
   - KPI "Veículos": dois valores com `<sc-if>`/markup direto; divisória vertical entre eles.
   - Localização: `<sc-for list="{{ locRows }}" as="l">` com barra horizontal
     (`--surface-sunken` trilho, `--maas-verde` preenchimento, `width:{{ l.pct }}`).
   - Tipo de veículos: `<sc-for list="{{ tipoVeicRows }}" as="t">` com barra empilhada
     (dois `<span>` inline-flex, larguras `{{ t.mobPct }}` e `{{ t.naoPct }}`) + legenda.

3. **Layout/encaixe**: manter 16:9 sem rolagem. Se necessário, transformar a linha 2 em
   `grid-template-columns` de 3 colunas ou reduzir `flex` dos tiles do bloco 04. Verificar que
   nada estoura 1080px (o container tem `overflow:hidden`).

4. **Ícones**: usar o helper `this.ic(nome, tamanho, cor)` já existente. Sugestões de ícone
   Lucide (adicionar ao mapa `M` se não existir): `truck` (frota), `mapPin` (localização),
   `car` (veículos). Cor `--maas-verde` nos cabeçalhos.

## Critérios de aceite
- [ ] KPI "Veículos" mostra 48 Mobilizados e 5 Não mobilizados, com indicador verde.
- [ ] "Localização dos veículos": barras 41 (interna) e 14 (externa).
- [ ] "Tipo de veículos": barras Pesada 32 e Leve 16, com legenda mobilizado × não mobilizado.
- [ ] Tudo em tokens MaaS, estilos inline, sem quebrar o 16:9 / auto-scale / drill-down.
- [ ] Sem erros de console; painel continua cabendo na TV sem rolagem.
