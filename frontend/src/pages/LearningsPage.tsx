import { useState } from "react";
import { useParams } from "react-router";
import {
  useLearnings,
  useRecordLearning,
  useRecallLearnings,
  useLearningFeedback,
} from "@/api/hooks/useLearnings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { EmptyState } from "@/components/shared/EmptyState";
import { TabGroup } from "@/components/ui/tabs";
import { BookOpen, Plus, Search, ThumbsUp, ThumbsDown } from "lucide-react";

const LEARNING_TYPES = ["pattern", "convention", "gotcha", "context", "decision"] as const;
type LearningType = (typeof LEARNING_TYPES)[number];

const TYPE_COLORS: Record<LearningType, string> = {
  pattern: "bg-blue-500/15 text-blue-400 border-blue-500/20",
  convention: "bg-green-500/15 text-green-400 border-green-500/20",
  gotcha: "bg-red-500/15 text-red-400 border-red-500/20",
  context: "bg-purple-500/15 text-purple-400 border-purple-500/20",
  decision: "bg-amber-500/15 text-amber-400 border-amber-500/20",
};

const TYPE_FILTER_TABS = ["All", ...LEARNING_TYPES.map((t) => t.charAt(0).toUpperCase() + t.slice(1))] as const;

export function LearningsPage() {
  const { repoId } = useParams();
  const [typeFilter, setTypeFilter] = useState<string>("All");
  const [scopeFilter, setScopeFilter] = useState("");
  const learnings = useLearnings(repoId!, {
    type: typeFilter === "All" ? "" : typeFilter.toLowerCase(),
    scope: scopeFilter || undefined,
  });
  const recordLearning = useRecordLearning(repoId!);
  const recallLearnings = useRecallLearnings(repoId!);
  const learningFeedback = useLearningFeedback(repoId!);

  // Record form state
  const [type, setType] = useState<LearningType>("pattern");
  const [description, setDescription] = useState("");
  const [scope, setScope] = useState("");
  const [confidence, setConfidence] = useState(0.7);
  const [showForm, setShowForm] = useState(false);

  // Search state
  const [searchQuery, setSearchQuery] = useState("");

  const handleRecord = () => {
    if (!description.trim()) return;
    recordLearning.mutate(
      {
        type,
        description: description.trim(),
        scope: scope || undefined,
        confidence,
      },
      {
        onSuccess: () => {
          setDescription("");
          setScope("");
          setConfidence(0.7);
          setShowForm(false);
        },
      },
    );
  };

  const handleSearch = () => {
    if (!searchQuery.trim()) return;
    recallLearnings.mutate(searchQuery.trim());
  };

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <BookOpen className="h-5 w-5 text-muted-foreground" />
          <h2 className="text-xl font-semibold">Knowledge Base</h2>
          {learnings.data && (
            <span className="text-sm text-muted-foreground">
              {learnings.data.length} entries
            </span>
          )}
        </div>
        <Button size="sm" variant="outline" onClick={() => setShowForm(!showForm)}>
          <Plus className="h-4 w-4" />
          Record
        </Button>
      </div>

      {/* Record Form (collapsed by default) */}
      {showForm && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Record a Learning</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex gap-3">
              <div className="w-48">
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Type</label>
                <select
                  value={type}
                  onChange={(e) => setType(e.target.value as LearningType)}
                  className="flex h-9 w-full rounded-md border border-border bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/50"
                >
                  {LEARNING_TYPES.map((t) => (
                    <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
                  ))}
                </select>
              </div>
              <div className="flex-1">
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Scope</label>
                <Input placeholder="e.g. src/api, global" value={scope} onChange={(e) => setScope(e.target.value)} />
              </div>
              <div className="w-40">
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  Confidence: {confidence.toFixed(1)}
                </label>
                <input
                  type="range"
                  min={0} max={1} step={0.1}
                  value={confidence}
                  onChange={(e) => setConfidence(parseFloat(e.target.value))}
                  className="mt-2 h-2 w-full cursor-pointer appearance-none rounded-lg bg-border accent-primary"
                />
              </div>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Description</label>
              <textarea
                placeholder="What did you learn about this codebase?"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                className="flex w-full rounded-md border border-border bg-transparent px-3 py-2 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/50 resize-none"
              />
            </div>
            <div className="flex gap-2 justify-end">
              <Button variant="ghost" size="sm" onClick={() => setShowForm(false)}>Cancel</Button>
              <Button size="sm" onClick={handleRecord} disabled={recordLearning.isPending || !description.trim()}>
                {recordLearning.isPending ? "Recording..." : "Record"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Type filter tabs */}
      <TabGroup items={TYPE_FILTER_TABS} value={typeFilter as typeof TYPE_FILTER_TABS[number]} onChange={setTypeFilter} />

      {/* Scope filter */}
      <div className="flex gap-3 items-center">
        <Input
          placeholder="Filter by scope..."
          value={scopeFilter}
          onChange={(e) => setScopeFilter(e.target.value)}
          className="w-64 h-8 text-xs"
        />
      </div>

      {/* Search / Recall */}
      <Card>
        <CardContent className="pt-4 pb-4">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Search knowledge base with natural language..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                className="pl-9"
              />
            </div>
            <Button variant="outline" size="sm" onClick={handleSearch} disabled={recallLearnings.isPending || !searchQuery.trim()}>
              {recallLearnings.isPending ? "Searching..." : "Search"}
            </Button>
          </div>
          {recallLearnings.data && recallLearnings.data.results.length > 0 && (
            <div className="mt-4 space-y-2">
              {recallLearnings.data.results.map((item) => (
                <div key={item.id} className="rounded-md border border-border bg-muted/30 p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge className={TYPE_COLORS[item.type as LearningType] ?? TYPE_COLORS.context}>
                      {item.type}
                    </Badge>
                    {item.scope && <span className="text-xs text-muted-foreground font-mono">{item.scope}</span>}
                    <Badge variant="outline" className="ml-auto text-[10px] tabular-nums">
                      {(item.relevance_score * 100).toFixed(0)}% relevant
                    </Badge>
                  </div>
                  <p className="text-sm">{item.description}</p>
                </div>
              ))}
            </div>
          )}
          {recallLearnings.data && recallLearnings.data.results.length === 0 && (
            <p className="mt-3 text-sm text-muted-foreground">No relevant learnings found.</p>
          )}
        </CardContent>
      </Card>

      {/* Learnings List */}
      {learnings.isLoading ? (
        <LoadingSpinner />
      ) : !learnings.data?.length ? (
        <EmptyState
          icon={<BookOpen className="h-12 w-12" />}
          title="No entries found"
          description={typeFilter !== "All" ? `No ${typeFilter.toLowerCase()} learnings recorded` : "Record patterns, conventions, and gotchas you discover about this codebase"}
          action={
            <Button onClick={() => setShowForm(true)}>
              <Plus className="h-4 w-4" />
              Record your first learning
            </Button>
          }
        />
      ) : (
        <div className="space-y-3">
          {learnings.data.map((learning) => (
            <Card key={learning.id}>
              <CardContent className="flex items-start gap-4 py-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge className={TYPE_COLORS[learning.type as LearningType] ?? TYPE_COLORS.context}>
                      {learning.type}
                    </Badge>
                    {learning.scope && (
                      <span className="text-xs text-muted-foreground font-mono">{learning.scope}</span>
                    )}
                    <span className="text-xs text-muted-foreground">#{learning.id}</span>
                  </div>
                  <p className="text-sm">{learning.description}</p>
                  <div className="mt-2 flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">Confidence:</span>
                    <div className="h-2 w-24 rounded-full bg-border overflow-hidden">
                      <div
                        className="h-full rounded-full bg-primary transition-all"
                        style={{ width: `${learning.confidence * 100}%` }}
                      />
                    </div>
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {(learning.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
                <div className="flex gap-1 shrink-0">
                  <button
                    onClick={() => learningFeedback.mutate({ learningId: learning.id, helpful: true })}
                    className="rounded p-1.5 text-muted-foreground hover:bg-green-500/10 hover:text-green-400 transition-colors"
                    title="Helpful"
                  >
                    <ThumbsUp className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => learningFeedback.mutate({ learningId: learning.id, helpful: false })}
                    className="rounded p-1.5 text-muted-foreground hover:bg-red-500/10 hover:text-red-400 transition-colors"
                    title="Not helpful"
                  >
                    <ThumbsDown className="h-4 w-4" />
                  </button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
