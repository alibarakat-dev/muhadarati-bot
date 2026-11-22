(async () => {
  if (!location.hostname.endsWith("wiu.edu.sy")) { alert("افتح صفحة المحاضرات بموقع الجامعة أولاً"); return; }
  const KEY = "wadibyte_done", FAC = 4, CODE = /^[A-Z]{2,5}\d{2,4}[A-Z]?$/;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let done;
  try { done = new Set(JSON.parse(localStorage.getItem(KEY) || "[]")); } catch (e) { done = new Set(); }
  const found = [...new Set(document.body.innerText.match(/\b[A-Z]{2,5}\d{3}[A-Z]?\b/g) || [])];
  const input = prompt("أكواد المواد (عدّل إذا بدك):", found.join(","));
  if (!input) return;
  const codes = input.toUpperCase().split(/[,\s]+/).filter(c => CODE.test(c));
  let n = 0, err = 0;
  for (const c of codes) {
    try {
      const r = await fetch(new URL("getlectures.php?course=" + encodeURIComponent(c), location.href));
      if (!r.ok) { err++; continue; }
      const files = (await r.text()).split(",").map(s => s.trim()).filter(s => /\.(pdf|pptx?|docx?)$/i.test(s) && !s.includes("/"));
      for (const f of files) {
        const k = c + "/" + f;
        if (done.has(k)) continue;
        const fr = await fetch("/lectures/" + FAC + "/" + c + "/" + encodeURIComponent(f));
        if (!fr.ok) { err++; continue; }
        const a = document.createElement("a");
        a.href = URL.createObjectURL(await fr.blob());
        a.download = c + " - " + f;
        document.body.appendChild(a); a.click(); a.remove();
        done.add(k); n++;
        localStorage.setItem(KEY, JSON.stringify([...done]));
        await sleep(1500);
      }
    } catch (e) { err++; }
    await sleep(1000);
  }
  alert("✅ نزل " + n + " ملف جديد" + (err ? "\n⚠️ " + err + " فشلوا، جرّب بعدين" : "") + "\nهلق اسحبهن كلهن للبوت 📥");
})();
