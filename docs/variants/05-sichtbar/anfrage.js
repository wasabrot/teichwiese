// Kurzanfrage mit vorgefertigten Sätzen.
// Entscheid 18.11.2026: Zustellung per E-Mail über ein eigenes Backend auf der Homepage (folgt später).
// Dann data-endpoint am Formular setzen; bis dahin Testmodus.
// Versandweg über Attribute am Formular:
//   data-endpoint="https://…"  → POST (JSON) an einen Formular-Dienst; Erfolg nur bei HTTP 2xx
//   data-mail="name@domain"    → öffnet das E-Mail-Programm mit fertiger Nachricht
//   beides leer                → Testversion: zeigt die Nachricht, sendet nichts
(function () {
  const form = document.getElementById("quick");
  if (!form) return;
  const status = form.querySelector(".status");
  const preview = form.querySelector(".preview");
  const pre = preview.querySelector("pre");
  const contact = form.elements.kontakt;

  const isMail = (v) => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v);
  const isPhone = (v) => (v.replace(/[^\d]/g, "").length >= 6) && /^[+\d\s()/.-]+$/.test(v);

  function data() {
    const anliegen = [...form.querySelectorAll('input[name="anliegen"]:checked')].map((i) => i.value);
    return {
      anliegen,
      kontakt: contact.value.trim(),
      name: form.elements.name.value.trim(),
      nachricht: form.elements.nachricht.value.trim(),
      seite: location.pathname,
    };
  }

  function text(d) {
    const lines = ["Interesse an der Teichwiese", ""];
    (d.anliegen.length ? d.anliegen : ["Bitte kontaktieren Sie mich."]).forEach((a) => lines.push("• " + a));
    if (d.nachricht) lines.push("", d.nachricht);
    lines.push("", "Kontakt: " + d.kontakt);
    if (d.name) lines.push("Name/Firma: " + d.name);
    return lines.join("\n");
  }

  function say(msg, kind) {
    status.textContent = msg;
    status.dataset.kind = kind || "";
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const d = data();
    if (!isMail(d.kontakt) && !isPhone(d.kontakt)) {
      say("Bitte geben Sie eine Telefonnummer oder E-Mail-Adresse an.", "error");
      contact.focus();
      return;
    }
    const msg = text(d);
    const endpoint = form.dataset.endpoint;
    const mail = form.dataset.mail;
    if (endpoint) {
      const btn = form.querySelector("button");
      btn.disabled = true;
      say("Wird gesendet …");
      try {
        const res = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ ...d, text: msg }),
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        say("Danke! Ihre Anfrage ist angekommen. Wir melden uns bei Ihnen.", "ok");
        form.reset();
        preview.hidden = true;
      } catch (e) {
        say("Das Senden hat leider nicht geklappt. Bitte versuchen Sie es später noch einmal.", "error");
      } finally {
        btn.disabled = false;
      }
    } else if (mail) {
      const href = "mailto:" + mail + "?subject=" + encodeURIComponent("Interesse Teichwiese") +
        "&body=" + encodeURIComponent(msg);
      location.href = href;
      say("Ihr E-Mail-Programm öffnet sich mit der fertigen Nachricht – bitte dort noch auf Senden tippen.");
    } else {
      pre.textContent = msg;
      preview.hidden = false;
      say("Testversion: Der Versand ist noch nicht freigeschaltet. So würde Ihre Anfrage lauten:", "info");
    }
  });

  contact.addEventListener("input", () => {
    if (status.dataset.kind === "error") say("");
  });
})();
