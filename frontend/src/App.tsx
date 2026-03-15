import { BrowserRouter, Routes, Route, Navigate } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { AuthGuard } from "@/components/auth/AuthGuard";
import { AppShell } from "@/components/layout/AppShell";

// Pages
import { LoginPage } from "@/pages/LoginPage";
import { RegisterPage } from "@/pages/RegisterPage";
import { OAuthCallbackPage } from "@/pages/OAuthCallbackPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { RepoDetailPage } from "@/pages/RepoDetailPage";
import { FileBrowserPage } from "@/pages/FileBrowserPage";
import { CommitHistoryPage } from "@/pages/CommitHistoryPage";
import { CommitDetailPage } from "@/pages/CommitDetailPage";
import { SearchPage } from "@/pages/SearchPage";
import { AnalysisPage } from "@/pages/AnalysisPage";
import { GraphPage } from "@/pages/GraphPage";
import { EmbeddingsPage } from "@/pages/EmbeddingsPage";
import { SecurityPage } from "@/pages/SecurityPage";
import { LearningsPage } from "@/pages/LearningsPage";
import { BranchComparePage } from "@/pages/BranchComparePage";
import { SettingsPage } from "@/pages/SettingsPage";
import { ActivityPage } from "@/pages/ActivityPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        <BrowserRouter>
          <Routes>
            {/* Public routes */}
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/auth/callback" element={<OAuthCallbackPage />} />

            {/* Authenticated routes */}
            <Route
              element={
                <AuthGuard>
                  <AppShell />
                </AuthGuard>
              }
            >
              <Route index element={<DashboardPage />} />

              {/* Repo routes */}
              <Route
                path="orgs/:orgId/repos/:repoId"
                element={<RepoDetailPage />}
              >
                <Route index element={<Navigate to="files" replace />} />
                <Route path="files/*" element={<FileBrowserPage />} />
                <Route path="commits" element={<CommitHistoryPage />} />
                <Route path="commits/:sha" element={<CommitDetailPage />} />
                <Route path="search" element={<SearchPage />} />
                <Route path="analysis" element={<AnalysisPage />} />
                <Route path="graph" element={<GraphPage />} />
                <Route path="embeddings" element={<EmbeddingsPage />} />
                <Route path="security" element={<SecurityPage />} />
                <Route path="learnings" element={<LearningsPage />} />
                <Route path="compare" element={<BranchComparePage />} />
              </Route>

              {/* Org routes */}
              <Route path="orgs/:orgId/settings" element={<SettingsPage />} />
              <Route path="orgs/:orgId/activity" element={<ActivityPage />} />
            </Route>

            {/* Catch-all */}
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </BrowserRouter>
      </ErrorBoundary>
    </QueryClientProvider>
  );
}
