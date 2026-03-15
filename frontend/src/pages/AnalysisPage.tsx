import { useState, useRef, useEffect } from "react";
import { useParams, useNavigate } from "react-router";
import {
  useSymbols,
  useHotspots,
  useConventions,
  useImpactAnalysis,
  useCommunities,
} from "@/api/hooks/useAnalysis";
import { useFileTree } from "@/api/hooks/useFiles";
import { FileTree } from "@/components/code/FileTree";
import { SymbolList } from "@/components/analysis/SymbolList";
import {
  FileHotspotsTable,
  FunctionHotspotsTable,
  OrphanFilesList,
} from "@/components/analysis/HotspotsTable";
import { ConventionsPanelNew } from "@/components/analysis/ConventionsPanel";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { EmptyState } from "@/components/shared/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TabGroup } from "@/components/ui/tabs";
import { cn } from "@/lib/cn";
import {
  FileCode2,
  ChevronDown,
  ChevronRight,
  Waypoints,
  Boxes,
  FolderSearch,
  X,
  Info,
  Flame,
} from "lucide-react";

const TABS = [
  "Symbols",
  "Hotspots",
  "Conventions",
  "Impact",
  "Communities",
] as const;

export function AnalysisPage() {
  const { orgId, repoId } = useParams();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Symbols");
  const symbols = useSymbols(repoId!);
  const hotspots = useHotspots(repoId!);
  const conventions = useConventions(repoId!);

  return (
    <div className="space-y-6">
      <TabGroup items={TABS} value={tab} onChange={setTab} />

      {tab === "Symbols" &&
        (symbols.isLoading ? (
          <LoadingSpinner />
        ) : (
          <SymbolList symbols={symbols.data?.symbols ?? []} repoId={repoId!} />
        ))}

      {tab === "Hotspots" && <HotspotsTab repoId={repoId!} hotspots={hotspots} />}

      {tab === "Conventions" && <ConventionsTab repoId={repoId!} conventions={conventions} />}

      {tab === "Impact" && <ImpactTab orgId={orgId!} repoId={repoId!} />}

      {tab === "Communities" && <CommunitiesTab repoId={repoId!} />}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Hotspots Tab                                                       */
/* ------------------------------------------------------------------ */

function HotspotsTab({ hotspots }: { repoId: string; hotspots: ReturnType<typeof useHotspots> }) {
  if (hotspots.isLoading) return <LoadingSpinner />;

  const data = hotspots.data;
  if (!data || data.file_hotspots.length === 0) {
    return (
      <EmptyState
        icon={<Flame className="h-12 w-12" />}
        title="No hotspots found"
        description="Hotspots will appear after the repository is indexed."
      />
    );
  }

  return (
    <div className="space-y-8 max-w-5xl">
      {/* File Hotspots */}
      <section>
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Flame className="h-4 w-4" />
          File Hotspots
          <Badge variant="secondary" className="text-[10px]">{data.file_hotspots.length}</Badge>
        </h3>
        <FileHotspotsTable hotspots={data.file_hotspots} />
      </section>

      {/* Function Hotspots */}
      {data.function_hotspots.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            Function Hotspots
            <Badge variant="secondary" className="text-[10px]">{data.function_hotspots.length}</Badge>
          </h3>
          <FunctionHotspotsTable hotspots={data.function_hotspots} />
        </section>
      )}

      {/* Orphan Files */}
      {data.orphan_files.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            Orphan Files
            <Badge variant="destructive" className="text-[10px]">{data.orphan_files.length}</Badge>
          </h3>
          <OrphanFilesList files={data.orphan_files} />
        </section>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Conventions Tab                                                    */
/* ------------------------------------------------------------------ */

function ConventionsTab({ repoId, conventions }: { repoId: string; conventions: ReturnType<typeof useConventions> }) {
  const [dirPath, setDirPath] = useState("");
  const filteredConventions = useConventions(repoId, dirPath || undefined);
  const activeData = dirPath ? filteredConventions : conventions;

  if (activeData.isLoading) return <LoadingSpinner />;

  if (!activeData.data) {
    return (
      <EmptyState
        icon={<Info className="h-12 w-12" />}
        title="No conventions data"
        description="Convention analysis requires indexed source files."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <label className="text-xs font-medium text-muted-foreground">Directory:</label>
        <input
          type="text"
          value={dirPath}
          onChange={(e) => setDirPath(e.target.value)}
          placeholder="All (or e.g. src/api)"
          className="h-8 w-64 rounded-md border border-input bg-background px-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
        />
      </div>
      <ConventionsPanelNew data={activeData.data} />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Impact Tab                                                         */
/* ------------------------------------------------------------------ */

const DEPTH_COLORS = [
  "border-red-500/30 bg-red-500/10 text-red-300",
  "border-orange-500/30 bg-orange-500/10 text-orange-300",
  "border-amber-500/30 bg-amber-500/10 text-amber-300",
  "border-yellow-500/30 bg-yellow-500/10 text-yellow-300",
  "border-green-500/30 bg-green-500/10 text-green-300",
];

function ImpactTab({ orgId, repoId }: { orgId: string; repoId: string }) {
  const navigate = useNavigate();
  const impact = useImpactAnalysis(repoId);
  const fileTree = useFileTree(orgId, repoId);
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [textInput, setTextInput] = useState("");
  const [showBrowser, setShowBrowser] = useState(false);
  const browserRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showBrowser) return;
    const handler = (e: MouseEvent) => {
      if (browserRef.current && !browserRef.current.contains(e.target as Node)) {
        setShowBrowser(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showBrowser]);

  const addFile = (path: string) => {
    if (!selectedFiles.includes(path)) {
      setSelectedFiles((prev) => [...prev, path]);
    }
  };

  const removeFile = (path: string) => {
    setSelectedFiles((prev) => prev.filter((f) => f !== path));
  };

  const handleTextAdd = () => {
    const paths = textInput.split(",").map((f) => f.trim()).filter(Boolean);
    for (const p of paths) addFile(p);
    setTextInput("");
  };

  const handleAnalyze = () => {
    if (selectedFiles.length > 0) {
      impact.mutate(selectedFiles);
    }
  };

  const handleFileClick = (file: string) => {
    navigate(`../files?path=${encodeURIComponent(file)}`);
  };

  const isTestFile = (f: string) => /test|spec|__test__|_test\./i.test(f);
  const isConfigFile = (f: string) => /(config|\.cfg|\.ini|\.toml|\.yaml|\.yml|\.json)$/i.test(f);

  return (
    <div className="space-y-5 max-w-4xl">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-lg">
            <Waypoints className="h-5 w-5" />
            Impact Analysis
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground leading-relaxed">
            Traces the dependency graph to find files affected by your changes.
            <strong className="text-foreground/80"> Direct</strong> = files that import changed files.
            Higher orders = transitive dependencies (files that import those files, and so on).
          </p>
          {selectedFiles.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {selectedFiles.map((f) => (
                <Badge key={f} variant="secondary" className="gap-1 pl-2 pr-1 font-mono text-xs">
                  {f}
                  <button onClick={() => removeFile(f)} className="ml-0.5 rounded-sm hover:bg-white/[0.08] p-0.5">
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              ))}
            </div>
          )}

          <div className="flex gap-2 items-start">
            <div className="flex-1 space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                Add files (comma-separated or browse)
              </label>
              <input
                type="text"
                value={textInput}
                onChange={(e) => setTextInput(e.target.value)}
                placeholder="e.g. src/main.py, src/utils.py"
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    if (textInput.trim()) handleTextAdd();
                    else handleAnalyze();
                  }
                }}
              />
            </div>
            <div className="relative pt-6" ref={browserRef}>
              <Button variant="outline" size="sm" onClick={() => setShowBrowser(!showBrowser)} className="gap-1.5">
                <FolderSearch className="h-4 w-4" />
                Browse
              </Button>
              {showBrowser && (
                <div className="absolute right-0 top-full z-50 mt-1 w-80 max-h-96 overflow-auto rounded-lg border border-border bg-background shadow-lg">
                  {fileTree.isLoading ? (
                    <div className="p-4"><LoadingSpinner /></div>
                  ) : fileTree.data?.tree ? (
                    <div className="p-1">
                      <FileTree nodes={fileTree.data.tree} onSelect={(path) => addFile(path)} selectedPath="" />
                    </div>
                  ) : (
                    <div className="p-4 text-sm text-muted-foreground">No files found</div>
                  )}
                </div>
              )}
            </div>
          </div>

          <Button onClick={handleAnalyze} disabled={impact.isPending || selectedFiles.length === 0} size="sm">
            {impact.isPending ? "Analyzing..." : "Analyze Impact"}
          </Button>
        </CardContent>
      </Card>

      {impact.isPending && <LoadingSpinner />}

      {impact.isError && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          <strong>Analysis failed:</strong> {impact.error?.message ?? "Unknown error"}
        </div>
      )}

      {impact.data && (
        <div className="space-y-4">
          {/* Summary bar with layer counts */}
          <div className="flex items-center gap-3 flex-wrap">
            <p className="text-sm text-muted-foreground">
              {impact.data.changed_files.length} changed file{impact.data.changed_files.length !== 1 ? "s" : ""}
            </p>
            {impact.data.layers && impact.data.layers.length > 0 ? (
              <>
                <div className="flex items-center gap-1">
                  {impact.data.layers.map((layer, i) => (
                    <Badge
                      key={layer.depth}
                      variant="outline"
                      className={cn("text-xs", DEPTH_COLORS[Math.min(i, DEPTH_COLORS.length - 1)])}
                    >
                      {layer.depth === 1 ? "Direct" : `Depth ${layer.depth}`}: {layer.files.length}
                    </Badge>
                  ))}
                </div>
                <Badge variant="default">{impact.data.total_impacted} total</Badge>
              </>
            ) : (
              <Badge variant="default">{impact.data.total_impacted} impacted</Badge>
            )}
          </div>

          {/* Impact flow visualization */}
          {impact.data.layers && impact.data.layers.length > 0 && (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground overflow-x-auto pb-1">
              <span className="rounded bg-primary/20 px-2 py-0.5 text-primary font-medium whitespace-nowrap">
                Changed ({impact.data.changed_files.length})
              </span>
              {impact.data.layers.map((layer, i) => (
                <span key={layer.depth} className="flex items-center gap-1.5">
                  <span className="text-muted-foreground/50">&rarr;</span>
                  <span className={cn(
                    "rounded px-2 py-0.5 font-medium whitespace-nowrap",
                    i === 0 ? "bg-red-500/20 text-red-400" : i === 1 ? "bg-orange-500/20 text-orange-400" : "bg-amber-500/20 text-amber-400",
                  )}>
                    {layer.depth === 1 ? "Direct" : `${layer.depth}${layer.depth === 2 ? "nd" : layer.depth === 3 ? "rd" : "th"}`} ({layer.files.length})
                  </span>
                </span>
              ))}
            </div>
          )}

          {/* Stacked bar visualization */}
          {impact.data.layers && impact.data.layers.length > 0 && impact.data.total_impacted > 0 && (
            <div className="flex h-8 w-full rounded-lg overflow-hidden">
              {impact.data.layers.map((layer, i) => {
                const pct = (layer.files.length / impact.data!.total_impacted) * 100;
                return (
                  <div
                    key={layer.depth}
                    className={cn(
                      "h-full flex items-center justify-center text-[10px] font-medium text-white/90 transition-all",
                      i === 0 ? "bg-red-500" : i === 1 ? "bg-orange-500" : i === 2 ? "bg-amber-500" : "bg-yellow-500",
                    )}
                    style={{ width: `${pct}%` }}
                    title={`Depth ${layer.depth}: ${layer.files.length} files`}
                  >
                    {pct > 12 && `${layer.files.length}`}
                  </div>
                );
              })}
            </div>
          )}

          {/* Layered accordion or flat list */}
          {impact.data.layers && impact.data.layers.length > 0 ? (
            <div className="space-y-3">
              {impact.data.layers.map((layer, i) => (
                <ImpactLayerCard
                  key={layer.depth}
                  depth={layer.depth}
                  files={layer.files}
                  colorClass={DEPTH_COLORS[Math.min(i, DEPTH_COLORS.length - 1)]!}
                  onFileClick={handleFileClick}
                  isTestFile={isTestFile}
                  isConfigFile={isConfigFile}
                />
              ))}
            </div>
          ) : impact.data.impacted_files.length > 0 ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Impacted Files</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-1">
                  {impact.data.impacted_files.map((file) => (
                    <li key={file}>
                      <button
                        onClick={() => handleFileClick(file)}
                        className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-mono text-muted-foreground hover:text-foreground hover:bg-white/[0.04] transition-colors w-full text-left"
                      >
                        <FileCode2 className="h-3.5 w-3.5 shrink-0" />
                        {file}
                      </button>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ) : (
            <EmptyState
              icon={<Waypoints className="h-12 w-12" />}
              title="No downstream impact"
              description="The changed files do not appear to affect other files in the dependency graph."
            />
          )}
        </div>
      )}

      {!impact.data && !impact.isPending && !impact.isError && (
        <EmptyState
          icon={<Waypoints className="h-12 w-12" />}
          title="Impact Analysis"
          description="Select files to discover which other files would be affected by changes."
        />
      )}
    </div>
  );
}

function ImpactLayerCard({
  depth,
  files,
  colorClass,
  onFileClick,
  isTestFile,
  isConfigFile,
}: {
  depth: number;
  files: string[];
  colorClass: string;
  onFileClick: (file: string) => void;
  isTestFile: (f: string) => boolean;
  isConfigFile: (f: string) => boolean;
}) {
  const [expanded, setExpanded] = useState(depth === 1);

  return (
    <Card className={cn("border", colorClass.split(" ")[0])}>
      <CardHeader className="cursor-pointer pb-2" onClick={() => setExpanded(!expanded)}>
        <CardTitle className="flex items-center gap-2 text-sm">
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          {depth === 1 ? "Directly imports changed files" : depth === 2 ? "2nd-order dependencies" : `${depth}th-order dependencies`}
          <Badge variant="secondary" className="text-[10px] ml-auto">{files.length} files</Badge>
        </CardTitle>
      </CardHeader>
      {expanded && (
        <CardContent>
          <ul className="space-y-1">
            {files.map((file) => (
              <li key={file}>
                <button
                  onClick={(e) => { e.stopPropagation(); onFileClick(file); }}
                  className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-mono text-muted-foreground hover:text-foreground hover:bg-white/[0.04] transition-colors w-full text-left"
                >
                  <FileCode2 className="h-3.5 w-3.5 shrink-0" />
                  {file}
                  {isTestFile(file) && (
                    <Badge variant="outline" className="text-[10px] ml-auto bg-green-500/10 text-green-400 border-green-500/20">test</Badge>
                  )}
                  {isConfigFile(file) && (
                    <Badge variant="outline" className="text-[10px] ml-auto bg-blue-500/10 text-blue-400 border-blue-500/20">config</Badge>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </CardContent>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Communities Tab                                                     */
/* ------------------------------------------------------------------ */

function CommunitiesTab({ repoId }: { repoId: string }) {
  const navigate = useNavigate();
  const communities = useCommunities(repoId);

  const handleFileClick = (file: string) => {
    navigate(`../files?path=${encodeURIComponent(file)}`);
  };

  if (communities.isLoading) return <LoadingSpinner />;

  if (communities.isError) {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
        <strong>Failed to load communities:</strong> {communities.error?.message ?? "Unknown error"}
      </div>
    );
  }

  const data = communities.data;

  if (!data || data.communities.length === 0) {
    return (
      <EmptyState
        icon={<Boxes className="h-12 w-12" />}
        title="No communities detected"
        description="Community detection requires a populated dependency graph. Try reindexing."
      />
    );
  }

  return (
    <div className="space-y-5 max-w-4xl">
      <div className="flex items-center gap-4">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <Boxes className="h-5 w-5" />
          Communities
        </h2>
        <Badge variant="outline">{data.method}</Badge>
        <div className="flex items-center gap-1.5">
          <span className="text-sm text-muted-foreground">
            Modularity: {data.modularity.toFixed(3)}
          </span>
          <span
            className="cursor-help text-muted-foreground"
            title="&gt;0.4 = good modular structure, &lt;0.2 = tightly coupled"
          >
            <Info className="h-3.5 w-3.5" />
          </span>
        </div>
      </div>

      <div className="space-y-3">
        {data.communities.map((community) => (
          <CommunityCard
            key={community.id}
            community={community}
            onFileClick={handleFileClick}
          />
        ))}
      </div>

      {/* Inter-community coupling */}
      {data.bridges && data.bridges.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Inter-Community Coupling</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {data.bridges
                .sort((a, b) => b.edge_count - a.edge_count)
                .map((bridge, i) => {
                  const srcName = data.communities.find((c) => c.id === bridge.source_id)?.theme || `#${bridge.source_id}`;
                  const tgtName = data.communities.find((c) => c.id === bridge.target_id)?.theme || `#${bridge.target_id}`;
                  return (
                    <div key={i} className="flex items-center gap-3 text-sm">
                      <span className="font-mono text-xs truncate max-w-[200px]">{srcName}</span>
                      <span className="text-muted-foreground">&harr;</span>
                      <span className="font-mono text-xs truncate max-w-[200px]">{tgtName}</span>
                      <Badge variant="outline" className="ml-auto tabular-nums">
                        {bridge.edge_count} edges
                      </Badge>
                      {bridge.edge_count > 10 && (
                        <span className="text-[10px] text-amber-400">consider defining interface</span>
                      )}
                    </div>
                  );
                })}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function CommunityCard({
  community,
  onFileClick,
}: {
  community: {
    id: number;
    files: string[];
    size: number;
    theme: string;
    internal_edges: number;
    external_edges: number;
    hub: string;
    hub_internal_degree: number;
    top_dirs: string[];
  };
  onFileClick: (file: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const totalEdges = community.internal_edges + community.external_edges;
  const cohesion = totalEdges > 0 ? community.internal_edges / totalEdges : 0;

  return (
    <Card>
      <CardHeader className="cursor-pointer pb-3" onClick={() => setExpanded(!expanded)}>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-sm">
            {expanded ? (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            )}
            {community.theme || `Community ${community.id}`}
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="secondary">{community.size} files</Badge>
            <Badge variant={cohesion >= 0.6 ? "success" : cohesion >= 0.3 ? "warning" : "destructive"}>
              {(cohesion * 100).toFixed(0)}% cohesion
            </Badge>
          </div>
        </div>
        <div className="flex items-center gap-4 text-xs text-muted-foreground mt-1 ml-8 flex-wrap">
          <span>Hub: <span className="font-mono text-foreground">{community.hub}</span></span>
          <span>Internal: {community.internal_edges}</span>
          <span>External: {community.external_edges}</span>
          {community.top_dirs && community.top_dirs.length > 0 && (
            <div className="flex gap-1">
              {community.top_dirs.map((d) => (
                <Badge key={d} variant="outline" className="text-[10px] font-mono">{d}</Badge>
              ))}
            </div>
          )}
          {cohesion < 0.3 && (
            <span className="text-amber-400 text-[10px]">Low cohesion -- consider splitting</span>
          )}
        </div>
      </CardHeader>
      {expanded && (
        <CardContent>
          <ul className="space-y-1">
            {community.files.map((file) => (
              <li key={file}>
                <button
                  onClick={(e) => { e.stopPropagation(); onFileClick(file); }}
                  className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-mono text-muted-foreground hover:text-foreground hover:bg-white/[0.04] transition-colors w-full text-left"
                >
                  <FileCode2 className="h-3.5 w-3.5 shrink-0" />
                  {file}
                </button>
              </li>
            ))}
          </ul>
        </CardContent>
      )}
    </Card>
  );
}
