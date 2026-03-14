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

import { useEffect, useRef, useState } from "react";
import type { ReactCodeMirrorRef } from "@uiw/react-codemirror";
import { EditorView } from "@codemirror/view";
import { EditorSelection } from "@codemirror/state";

interface FileViewerProps {
  content: string;
  path: string;
  className?: string;
  highlightLine?: number | null;
}

export function FileViewer({ content, path, className, highlightLine }: FileViewerProps) {
  const [extensions, setExtensions] = useState<Extension[]>([]);
  const editorRef = useRef<ReactCodeMirrorRef>(null);
  const lang = getLanguageFromPath(path);

  useEffect(() => {
    getLanguageExtension(lang).then((ext) => {
      setExtensions(ext ? [ext] : []);
    });
  }, [lang]);

  useEffect(() => {
    if (!highlightLine || highlightLine < 1) return;

    const tryScroll = () => {
      const view = editorRef.current?.view;
      if (!view) {
        // View not ready yet — try next frame
        rafId = requestAnimationFrame(tryScroll);
        return;
      }
      const lineCount = view.state.doc.lines;
      if (highlightLine > lineCount) return;
      const line = view.state.doc.line(highlightLine);
      view.dispatch({
        selection: EditorSelection.cursor(line.from),
        effects: EditorView.scrollIntoView(line.from, { y: "center" }),
      });
    };

    let rafId = requestAnimationFrame(tryScroll);
    return () => cancelAnimationFrame(rafId);
  }, [highlightLine, content]);

  return (
    <CodeMirror
      ref={editorRef}
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
