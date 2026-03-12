/**
 * Auto-generated API types.
 * Run `npm run generate-api` with the backend running to regenerate.
 *
 * Below are manually maintained types matching the backend Pydantic models.
 * Replace with openapi-typescript output when available.
 */

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface UserProfile {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
  auth_provider: string;
  orgs: { org_id: string; role: string }[];
}

export interface OrgResponse {
  id: string;
  name: string;
  slug: string;
  plan: string;
  created_at: string;
  member_count: number;
}

export interface OrgListResponse {
  organizations: OrgResponse[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface RepoResponse {
  id: string;
  name: string;
  clone_url: string | null;
  default_branch: string;
  language: string | null;
  index_status: string;
  last_indexed_at: string | null;
  created_at: string;
}

export interface RepoListResponse {
  repositories: RepoResponse[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface MemberResponse {
  user_id: string;
  email: string;
  name: string;
  role: string;
  accepted: boolean;
}

export interface MemberListResponse {
  members: MemberResponse[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface ApiKeyResponse {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
}

export interface ApiKeyCreateResponse {
  id: string;
  name: string;
  key: string;
  key_prefix: string;
  scopes: string[];
  created_at: string;
  expires_at: string | null;
}

export interface FileTreeNode {
  name: string;
  path: string;
  type: "file" | "directory";
  size?: number;
  language?: string;
  children?: FileTreeNode[];
}

export interface FileContent {
  path: string;
  content: string;
  language?: string;
  size: number;
  lines: number;
  encoding: string;
}

export interface CommitInfo {
  sha: string;
  message: string;
  author_name: string;
  author_email: string;
  authored_at: string;
  parents: string[];
}

export interface CommitDetail extends CommitInfo {
  files_changed: {
    path: string;
    status: string;
    additions: number;
    deletions: number;
  }[];
}

export interface DiffHunk {
  old_start: number;
  old_count: number;
  new_start: number;
  new_count: number;
  header: string;
  lines: { type: "context" | "add" | "delete"; content: string }[];
}

export interface FileDiff {
  path: string;
  old_path?: string;
  status: string;
  hunks: DiffHunk[];
}

export interface BlameEntry {
  sha: string;
  author: string;
  date: string;
  line_start: number;
  line_end: number;
  content: string;
}

export interface SearchResult {
  file: string;
  line: number;
  content: string;
  score: number;
  context?: string;
}

export interface SearchResultsResponse {
  results: SearchResult[];
  total: number;
  query: string;
  took_ms: number;
}

export interface SymbolInfo {
  name: string;
  kind: string;
  file: string;
  line: number;
  end_line?: number;
  signature?: string;
}

export interface HotspotEntry {
  file: string;
  score: number;
  commit_count: number;
  complexity: number;
  lines: number;
}

export interface ConventionEntry {
  category: string;
  pattern: string;
  examples: string[];
  confidence: number;
}

export interface ImpactNode {
  file: string;
  symbols: string[];
  impact_score: number;
}

export interface ImpactResult {
  source: string;
  affected: ImpactNode[];
  depth: number;
}

export interface CommunityInfo {
  id: number;
  files: string[];
  label?: string;
  cohesion: number;
}

export interface SecurityFinding {
  file: string;
  line: number;
  rule: string;
  severity: "info" | "warning" | "error" | "critical";
  message: string;
}

export interface DependencyGraphNode {
  id: string;
  label: string;
  type: string;
}

export interface DependencyGraphEdge {
  source: string;
  target: string;
  type: string;
}

export interface DependencyGraphResponse {
  nodes: DependencyGraphNode[];
  edges: DependencyGraphEdge[];
}

export interface EmbeddingStatus {
  total_files: number;
  embedded_files: number;
  coverage: number;
  last_updated: string | null;
}

export interface EmbeddingFileEntry {
  file: string;
  embedded: boolean;
  chunk_count: number;
  last_embedded_at: string | null;
}

export interface IndexingStatus {
  status: string;
  progress: number;
  files_processed: number;
  files_total: number;
  started_at: string | null;
  completed_at: string | null;
}

export interface ActivityEvent {
  id: string;
  org_id: string;
  event_type: string;
  user_id: string | null;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface ActivityListResponse {
  events: ActivityEvent[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface UserPreferences {
  theme: string;
  editor_font_size: number;
  editor_tab_size: number;
  show_line_numbers: boolean;
  [key: string]: unknown;
}

export interface PresenceEntry {
  user_id: string;
  user_name: string;
  file_path: string | null;
  last_seen: string;
}

export interface CrossRefResult {
  symbol: string;
  definitions: { file: string; line: number }[];
  references: { file: string; line: number }[];
}

export interface JobInfo {
  id: string;
  type: string;
  status: string;
  progress: number;
  created_at: string;
  completed_at: string | null;
  error: string | null;
}
