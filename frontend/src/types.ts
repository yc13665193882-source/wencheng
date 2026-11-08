export type ProtectedRange = { start: number; end: number; kind: string };
export type Block = {
  id: string; text: string; kind: string; style?: string;
  editable: boolean; protected: ProtectedRange[];
};
export type Annotation = {
  id: string; block_id: string; end_block_id?: string; start: number; end: number; quote: string;
  instruction: string; category?: string;
  status: 'pending' | 'suggested' | 'applied' | 'rejected' | 'conflict';
  replacement?: string; reason?: string; commented?: boolean;
};
export type Project = {
  id: string; title: string; version: number;
  blocks: Block[];
  protections: { kind: string; count: number }[];
  annotations: Annotation[];
  history: { id: string; label: string; at: string; version: number }[];
  settings: { rules: string; style_sample: string; language: string };
};
export type ProjectSummary = { id: string; title: string; updated_at: string };
export type Selection = { block_id: string; end_block_id?: string; start: number; end: number; quote: string };
export type ProviderConfig = { provider: string; model: string; base_url: string; api_key_env: string };
export type ProviderInfo = { id: string; label: string; available: boolean };
export type Job = { status: 'running' | 'done' | 'error'; progress: string | number; error?: string; project_id: string };
