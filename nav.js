// Barra de navegación común. Es opcional: si no carga (por ejemplo, al abrir un HTML suelto), la demo funciona igual.
(function () {
  var base = new URL('.', document.currentScript.src).pathname;
  var links = [
    ['Inicio', base],
    ['Calculadora', base + 'calculadora_combustible.html'],
    ['Configurador', base + 'configurador_bomba.html'],
    ['Flota simulada', base + 'dashboard_flota.html'],
    ['Telemetría en vivo', base + 'consola/'],
    ['Grafana', base + 'grafana/d/qm-flota'],
    ['Arquitectura', base + 'arquitectura.html'],
    ['Propuesta PDF', base + 'propuesta_demos.pdf'],
  ];
  var here = location.pathname.replace(/index\.html$/, '');
  var css = document.createElement('style');
  css.textContent =
    '#qmnav{position:fixed;inset:0 0 auto 0;z-index:1000;height:44px;display:flex;align-items:center;gap:4px;' +
    'padding:0 12px;background:#0b0e13;border-bottom:1px solid #2a303a;font:13px/1 system-ui,"Segoe UI",sans-serif;' +
    'overflow-x:auto;white-space:nowrap}' +
    '#qmnav b{color:#e8ebf0;margin-right:10px}' +
    '#qmnav a{color:#9aa3b2;text-decoration:none;padding:7px 10px;border-radius:7px}' +
    '#qmnav a:hover{color:#e8ebf0;background:#171b22}#qmnav a.on{color:#04121c;background:#38bdf8;font-weight:600}' +
    '#qmnav span{margin-left:auto;color:#6b7482;font-size:11px;padding-left:12px}' +
    '#qmnav-pad{height:44px}button.theme{top:56px!important}' +
    '@media print{#qmnav,#qmnav-pad{display:none}}';
  document.head.appendChild(css);
  var nav = document.createElement('nav');
  nav.id = 'qmnav';
  nav.innerHTML = '<b>QM · demos</b>' + links.map(function (l) {
    var on = here === l[1] || (l[1] !== base && here.indexOf(l[1].replace(/d\/qm-flota$/, '')) === 0);
    return '<a href="' + l[1] + '"' + (on ? ' class="on"' : '') + '>' + l[0] + '</a>';
  }).join('') + '<span>Demo independiente de Rober Palestini · no es un sitio oficial de QM Equipment</span>';
  var pad = document.createElement('div');
  pad.id = 'qmnav-pad';
  document.body.prepend(pad);
  document.body.prepend(nav);
})();
