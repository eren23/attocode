import { useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { useSearch } from "@/api/hooks/useSearch";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { SearchBar } from "@/components/search/SearchBar";
import { SearchResults } from "@/components/search/SearchResults";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { EmptyState } from "@/components/shared/EmptyState";
import { Search } from "lucide-react";

export function SearchPage() {
  const { repoId } = useParams();
  const [searchParams] = useSearchParams();
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [fileFilter, setFileFilter] = useState("");
  const debouncedQuery = useDebouncedValue(query, 400);
  const debouncedFilter = useDebouncedValue(fileFilter, 400);
  const search = useSearch(repoId!, debouncedQuery, { fileFilter: debouncedFilter || undefined });

  return (
    <div className="space-y-6 max-w-4xl">
      <SearchBar
        value={query}
        onChange={setQuery}
        fileFilter={fileFilter}
        onFileFilterChange={setFileFilter}
      />

      {search.isFetching && <LoadingSpinner />}

      {search.data && search.data.results.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">
            {search.data.total} results for &ldquo;{search.data.query}&rdquo;
            {debouncedFilter && <span> matching <code className="text-xs">{debouncedFilter}</code></span>}
          </p>
          <SearchResults results={search.data.results} repoId={repoId!} query={search.data.query} />
        </div>
      )}

      {search.data && search.data.results.length === 0 && debouncedQuery && (
        <EmptyState
          icon={<Search className="h-12 w-12" />}
          title="No results"
          description={`No matches for "${debouncedQuery}". Check the Embeddings page to verify indexing is complete.`}
        />
      )}

      {!search.data && !search.isFetching && (
        <EmptyState
          icon={<Search className="h-12 w-12" />}
          title="Search your codebase"
          description="Use natural language or code patterns to find what you need"
        />
      )}
    </div>
  );
}
