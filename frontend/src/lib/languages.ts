export const LANGUAGE_MAP: Record<
  string,
  { color: string; icon: string; ext: string[] }
> = {
  typescript: {
    color: "#3178c6",
    icon: "TS",
    ext: [".ts", ".tsx", ".mts", ".cts"],
  },
  javascript: {
    color: "#f7df1e",
    icon: "JS",
    ext: [".js", ".jsx", ".mjs", ".cjs"],
  },
  python: { color: "#3776ab", icon: "Py", ext: [".py", ".pyi"] },
  rust: { color: "#dea584", icon: "Rs", ext: [".rs"] },
  go: { color: "#00add8", icon: "Go", ext: [".go"] },
  java: { color: "#b07219", icon: "Jv", ext: [".java"] },
  cpp: { color: "#f34b7d", icon: "C+", ext: [".cpp", ".cc", ".cxx", ".hpp"] },
  c: { color: "#555555", icon: "C", ext: [".c", ".h"] },
  ruby: { color: "#cc342d", icon: "Rb", ext: [".rb"] },
  php: { color: "#4f5d95", icon: "Ph", ext: [".php"] },
  css: { color: "#563d7c", icon: "Cs", ext: [".css", ".scss", ".sass"] },
  html: { color: "#e34c26", icon: "Ht", ext: [".html", ".htm"] },
  json: { color: "#292929", icon: "Js", ext: [".json", ".jsonc"] },
  yaml: { color: "#cb171e", icon: "Ym", ext: [".yml", ".yaml"] },
  markdown: { color: "#083fa1", icon: "Md", ext: [".md", ".mdx"] },
  sql: { color: "#e38c00", icon: "Sq", ext: [".sql"] },
  shell: { color: "#89e051", icon: "Sh", ext: [".sh", ".bash", ".zsh"] },
  xml: { color: "#0060ac", icon: "Xm", ext: [".xml", ".svg"] },
};

export function getLanguageFromPath(path: string): string | undefined {
  const ext = "." + path.split(".").pop()?.toLowerCase();
  for (const [lang, info] of Object.entries(LANGUAGE_MAP)) {
    if (info.ext.includes(ext)) return lang;
  }
  return undefined;
}

export function getLanguageColor(lang: string): string {
  return LANGUAGE_MAP[lang]?.color ?? "#6b7280";
}
