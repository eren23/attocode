document$.subscribe(function() {
  mermaid.initialize({
    startOnLoad: false,
    theme: document.body.getAttribute("data-md-color-scheme") === "slate" ? "dark" : "default",
  });
  document.querySelectorAll("pre.mermaid > code").forEach(function(codeEl) {
    var pre = codeEl.parentElement;
    var div = document.createElement("div");
    div.classList.add("mermaid");
    div.textContent = codeEl.textContent;
    pre.parentElement.replaceChild(div, pre);
  });
  mermaid.run({ querySelector: ".mermaid" });
});
