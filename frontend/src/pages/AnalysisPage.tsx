import { useState } from "react";
import { useParams } from "react-router";
import { useSymbols, useHotspots, useConventions } from "@/api/hooks/useAnalysis";
import { SymbolList } from "@/components/analysis/SymbolList";
import { HotspotsTable } from "@/components/analysis/HotspotsTable";
import { ConventionsPanel } from "@/components/analysis/ConventionsPanel";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { cn } from "@/lib/cn";

const TABS = ["Symbols", "Hotspots", "Conventions"] as const;

export function AnalysisPage() {
  const { repoId } = useParams();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Symbols");
  const symbols = useSymbols(repoId!);
  const hotspots = useHotspots(repoId!);
  const conventions = useConventions(repoId!);

  return (
    <div className="space-y-6">
      <div className="flex gap-1 border-b border-border">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "border-b-2 px-4 py-2 text-sm transition-colors",
              t === tab
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Symbols" &&
        (symbols.isLoading ? (
          <LoadingSpinner />
        ) : (
          <SymbolList symbols={symbols.data?.symbols ?? []} />
        ))}

      {tab === "Hotspots" &&
        (hotspots.isLoading ? (
          <LoadingSpinner />
        ) : (
          <HotspotsTable hotspots={hotspots.data?.hotspots ?? []} />
        ))}

      {tab === "Conventions" &&
        (conventions.isLoading ? (
          <LoadingSpinner />
        ) : (
          <ConventionsPanel
            conventions={conventions.data?.conventions ?? []}
          />
        ))}
    </div>
  );
}
