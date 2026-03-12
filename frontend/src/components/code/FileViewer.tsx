import CodeMirror from "@uiw/react-codemirror";
import { oneDark } from "@codemirror/theme-one-dark";
import { getLanguageFromPath } from "@/lib/languages";
import type { Extension } from "@codemirror/state";

// Lazy language loading
async function getLanguageExtension(
  lang: string | undefined,
): Promise<Extension | null> {
  switch (lang) {
    case "typescript":
    case "javascript":
      return (await import("@codemirror/lang-javascript")).javascript({
        typescript: lang === "typescript",
        jsx: true,
      });
    case "python":
      return (await import("@codemirror/lang-python")).python();
    case "rust":
      return (await import("@codemirror/lang-rust")).rust();
    case "go":
      return (await import("@codemirror/lang-go")).go();
    case "java":
      return (await import("@codemirror/lang-java")).java();
    case "cpp":
    case "c":
      return (await import("@codemirror/lang-cpp")).cpp();
    case "css":
      return (await import("@codemirror/lang-css")).css();
    case "html":
      return (await import("@codemirror/lang-html")).html();
    case "json":
      return (await import("@codemirror/lang-json")).json();
    case "markdown":
      return (await import("@codemirror/lang-markdown")).markdown();
    case "sql":
      return (await import("@codemirror/lang-sql")).sql();
    case "xml":
      return (await import("@codemirror/lang-xml")).xml();
    case "yaml":
      return (await import("@codemirror/lang-yaml")).yaml();
    case "php":
      return (await import("@codemirror/lang-php")).php();
    default:
      return null;
  }
}

import { useEffect, useState } from "react";

interface FileViewerProps {
  content: string;
  path: string;
  className?: string;
}

export function FileViewer({ content, path, className }: FileViewerProps) {
  const [extensions, setExtensions] = useState<Extension[]>([]);
  const lang = getLanguageFromPath(path);

  useEffect(() => {
    getLanguageExtension(lang).then((ext) => {
      setExtensions(ext ? [ext] : []);
    });
  }, [lang]);

  return (
    <CodeMirror
      value={content}
      theme={oneDark}
      extensions={extensions}
      editable={false}
      basicSetup={{
        lineNumbers: true,
        foldGutter: true,
        highlightActiveLineGutter: true,
        highlightActiveLine: true,
      }}
      className={className}
    />
  );
}
