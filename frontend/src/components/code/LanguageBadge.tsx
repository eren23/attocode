import { getLanguageColor, LANGUAGE_MAP } from "@/lib/languages";

export function LanguageBadge({ language }: { language: string }) {
  const info = LANGUAGE_MAP[language];
  const color = getLanguageColor(language);

  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        className="h-2.5 w-2.5 rounded-full"
        style={{ backgroundColor: color }}
      />
      <span className="text-muted-foreground">
        {info?.icon ?? language}
      </span>
    </span>
  );
}
