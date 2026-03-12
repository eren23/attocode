import { useState } from "react";
import { useParams } from "react-router";
import { useSearchMutation } from "@/api/hooks/useSearch";
import { SearchBar } from "@/components/search/SearchBar";
import { SearchResults } from "@/components/search/SearchResults";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { EmptyState } from "@/components/shared/EmptyState";
import { Search } from "lucide-react";

export function SearchPage() {
  const { repoId } = useParams();
  const search = useSearchMutation(repoId!);
  const [query, setQuery] = useState("");

  const handleSearch = (q: string) => {
    setQuery(q);
    if (q.trim()) search.mutate(q);
  };

  return (
    <div className="space-y-6 max-w-4xl">
      <SearchBar onSearch={handleSearch} initialQuery={query} />

      {search.isPending && <LoadingSpinner />}

      {search.data && (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">
            {search.data.total} results in {search.data.took_ms}ms
          </p>
          <SearchResults results={search.data.results} />
        </div>
      )}

      {!search.data && !search.isPending && (
        <EmptyState
          icon={<Search className="h-12 w-12" />}
          title="Search your codebase"
          description="Use natural language or code patterns to find what you need"
        />
      )}
    </div>
  );
}
