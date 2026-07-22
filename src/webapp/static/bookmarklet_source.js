(function () {
  if (window.__gbpAuditCaptureActive) { return; }
  window.__gbpAuditCaptureActive = true;

  var API_BASE = "%%API_BASE%%";

  var bar = document.createElement("div");
  bar.style.cssText = "position:fixed;bottom:16px;right:16px;z-index:2147483647;background:#1c1f26;color:#fff;padding:10px 14px;border-radius:10px;font:14px -apple-system,Segoe UI,Roboto,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.35);display:flex;gap:8px;align-items:center;";

  var status = document.createElement("span");
  status.textContent = "gbp-audit: NAP-Angaben markieren, dann Übernehmen klicken";
  status.style.cssText = "margin-right:6px;";

  var btnUebernehmen = document.createElement("button");
  btnUebernehmen.textContent = "Übernehmen";
  btnUebernehmen.disabled = true;
  btnUebernehmen.style.cssText = "background:#2f5fd6;color:#fff;border:none;border-radius:6px;padding:6px 12px;cursor:pointer;opacity:.5;";

  var btnKeinEintrag = document.createElement("button");
  btnKeinEintrag.textContent = "Kein Eintrag vorhanden";
  btnKeinEintrag.style.cssText = "background:#555;color:#fff;border:none;border-radius:6px;padding:6px 12px;cursor:pointer;";

  var btnSchliessen = document.createElement("button");
  btnSchliessen.textContent = "×";
  btnSchliessen.title = "Schließen";
  btnSchliessen.style.cssText = "background:transparent;color:#fff;border:none;font-size:16px;cursor:pointer;margin-left:2px;";
  btnSchliessen.onclick = function () { bar.remove(); window.__gbpAuditCaptureActive = false; };

  bar.appendChild(status);
  bar.appendChild(btnUebernehmen);
  bar.appendChild(btnKeinEintrag);
  bar.appendChild(btnSchliessen);
  document.body.appendChild(bar);

  function aktuelleAuswahl() {
    var sel = window.getSelection ? window.getSelection().toString() : "";
    return (sel || "").trim();
  }

  document.addEventListener("selectionchange", function () {
    var text = aktuelleAuswahl();
    btnUebernehmen.disabled = !text;
    btnUebernehmen.style.opacity = text ? "1" : ".5";
  });

  function submit(action, text) {
    status.textContent = "Wird übernommen...";
    fetch(API_BASE + "/api/portal-capture/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: action, selected_text: text || "", source_url: location.href })
    }).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (data) {
        return { ok: resp.ok, data: data };
      });
    }).then(function (result) {
      if (result.ok) {
        status.textContent = "✓ Übernommen (" + (result.data.status_label || "gespeichert") + ")";
        btnUebernehmen.disabled = true;
        btnKeinEintrag.disabled = true;
        setTimeout(function () { bar.remove(); window.__gbpAuditCaptureActive = false; }, 4000);
      } else {
        status.textContent = "Fehler: " + (result.data.detail || "unbekannt") + " - bitte Text stattdessen manuell in der App einfügen.";
      }
    }).catch(function () {
      status.textContent = "Konnte nicht übertragen werden (evtl. von dieser Seite blockiert) - bitte Text stattdessen manuell in der App einfügen.";
    });
  }

  btnUebernehmen.onclick = function () { submit("uebernehmen", aktuelleAuswahl()); };
  btnKeinEintrag.onclick = function () { submit("kein_eintrag", ""); };
})();
