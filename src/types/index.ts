// Config types
export interface AppConfig {
  id: number;
  business_name?: string;
  tagline?: string;
  hero_text?: string;
  hero_image_url?: string;
  logo_url?: string;
  theme?: string;
  lakera_enabled: boolean;
  lakera_blocking_mode: boolean;
  use_litellm?: boolean;
  litellm_base_url?: string;
  litellm_guardrail_name?: string | null;
  litellm_guardrail_monitor_name?: string | null;
  rag_content_scanning: boolean;
  rag_lakera_project_id?: string;
  lakera_project_id?: string;
  openai_model: string;
  temperature: number;
  system_prompt?: string;
  openai_api_key?: string;
  litellm_virtual_key?: string;
  lakera_api_key?: string;
  // Multi-provider
  llm_provider?: string;
  anthropic_api_key?: string;
  google_api_key?: string;
  mistral_api_key?: string;
  groq_api_key?: string;
  together_api_key?: string;
  openrouter_api_key?: string;
  ollama_base_url?: string;
  // Multi-guardrail
  guardrail_provider?: string;
  bedrock_guardrail_id?: string;
  bedrock_guardrail_version?: string;
  bedrock_region?: string;
  bedrock_access_key_id?: string;
  bedrock_secret_access_key?: string;
  azure_content_safety_endpoint?: string;
  azure_content_safety_key?: string;
  palo_alto_api_key?: string;
  palo_alto_profile_name?: string;
  palo_alto_host?: string;
  // Portkey (LLM gateway)
  portkey_api_key?: string;
  portkey_virtual_key?: string;
  portkey_base_url?: string;
  // ThaiLLM (national Thai LLM gateway — OpenAI-compatible)
  thaillm_api_key?: string;
  thaillm_base_url?: string;
  // Cloudflare Firewall for AI
  cloudflare_account_id?: string;
  cloudflare_api_token?: string;
  cloudflare_gateway_id?: string;
  // Webhook
  webhook_url?: string;
  // Demo-safe lock — when true, provider config fields are read-only
  provider_config_locked?: boolean;
  created_at: string;
  updated_at: string;
}

export interface AppConfigUpdate {
  business_name?: string;
  tagline?: string;
  hero_text?: string;
  hero_image_url?: string;
  logo_url?: string;
  theme?: string;
  lakera_enabled: boolean;
  lakera_blocking_mode: boolean;
  use_litellm?: boolean;
  litellm_base_url?: string;
  litellm_guardrail_name?: string | null;
  litellm_guardrail_monitor_name?: string | null;
  rag_content_scanning: boolean;
  rag_lakera_project_id?: string;
  openai_model: string;
  temperature: number;
  system_prompt?: string;
  openai_api_key?: string;
  litellm_virtual_key?: string;
  lakera_api_key?: string;
  lakera_project_id?: string;
  // Multi-provider
  llm_provider?: string;
  anthropic_api_key?: string;
  google_api_key?: string;
  mistral_api_key?: string;
  groq_api_key?: string;
  together_api_key?: string;
  openrouter_api_key?: string;
  ollama_base_url?: string;
  // Multi-guardrail
  guardrail_provider?: string;
  bedrock_guardrail_id?: string;
  bedrock_guardrail_version?: string;
  bedrock_region?: string;
  bedrock_access_key_id?: string;
  bedrock_secret_access_key?: string;
  azure_content_safety_endpoint?: string;
  azure_content_safety_key?: string;
  palo_alto_api_key?: string;
  palo_alto_profile_name?: string;
  palo_alto_host?: string;
  // Portkey (LLM gateway)
  portkey_api_key?: string;
  portkey_virtual_key?: string;
  portkey_base_url?: string;
  // ThaiLLM (national Thai LLM gateway — OpenAI-compatible)
  thaillm_api_key?: string;
  thaillm_base_url?: string;
  // Cloudflare Firewall for AI
  cloudflare_account_id?: string;
  cloudflare_api_token?: string;
  cloudflare_gateway_id?: string;
  // Webhook
  webhook_url?: string;
  // Demo-safe lock — toggle whether provider config CRUD is allowed
  provider_config_locked?: boolean;
}

// Guardrail provider catalog (GET /api/guardrail-providers)
export interface GuardrailProviderField {
  name: string;
  label: string;
  type: 'text' | 'password';
  placeholder?: string;
}

export interface GuardrailProviderInfo {
  id: string;
  display_name: string;
  fields: GuardrailProviderField[];
  docs_url?: string | null;
  summary?: string | null;
}

// Multi-provider catalog (GET /api/providers)
export interface ProviderInfo {
  id: string;
  display_name: string;
  key_field: string | null;
  base_url_field: string | null;
  default_base_url?: string | null;
  needs_key: boolean;
  models: string[];
}

// Chat types
export interface ChatRequest {
  message: string;
  session_id?: string;
  prompt_id?: number;
}

export interface ChatResponse {
  response: string;
  lakera?: any;
  tool_traces?: any[];
  citations?: any[];
}

// RAG types
export interface RagGenerateRequest {
  industry: string;
  seed_prompt: string;
  preview_only: boolean;
}

export interface RagGenerateResponse {
  markdown: string;
  ingested: boolean;
}

export interface RagSearchResponse {
  chunks: any[];
}

// Tool types
export interface Tool {
  id: number;
  name: string;
  description?: string;
  endpoint?: string;
  type: string;
  enabled: boolean;
  config_json?: any;
  created_at: string;
  updated_at: string;
}

export interface ToolCreate {
  name: string;
  description?: string;
  endpoint?: string;
  type: string;
  enabled: boolean;
  config_json?: any;
}

export interface ToolUpdate extends ToolCreate {}

// Lakera types
export interface LakeraDetectorResult {
  project_id?: string;
  policy_id?: string;
  detector_id?: string;
  detector_type?: string;
  detected: boolean;
  message_id?: number;
}

export interface LakeraResult {
  payload: any[];
  flagged: boolean;
  dev_info?: any;
  metadata?: any;
  breakdown: LakeraDetectorResult[];
}

// Chat message types
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  tool_traces?: any[];
  lakera?: any;
}

// Demo Prompt types
export interface DemoPrompt {
  id: number;
  title: string;
  content: string;
  category: string;
  tags: string[];
  is_malicious: boolean;
  preferred_llm?: string;
  usage_count: number;
  created_at: string;
  updated_at: string;
}

export interface DemoPromptCreate {
  title: string;
  content: string;
  category: string;
  tags: string[];
  is_malicious: boolean;
  preferred_llm?: string | null;
}

export interface DemoPromptUpdate extends DemoPromptCreate {}

export interface DemoPromptSuggestion {
  text: string;
  full_content: string;
  title: string;
  category: string;
  is_malicious: boolean;
  prompt_id?: number;
  preferred_llm?: string;
}

export interface DemoPromptSearchResponse {
  prompts: DemoPrompt[];
  suggestions: DemoPromptSuggestion[];
}

// Scenario types (one-click demo company switcher)
export interface ScenarioPreview {
  id: string;
  industry: string;
  business_name: string;
  tagline: string;
  hero_text: string;
  theme: string;
  logo_url: string;
  hero_image_url: string;
}

export interface ApplyScenarioResponse {
  message: string;
  scenario_id: string;
  business_name: string;
  prompts_loaded: number;
}

// Detector labels mapping
export const DETECTOR_LABELS: Record<string, string> = {
  "prompt_attack": "Prompt Attack",
  "unknown_links": "Unknown Links",
  "moderated_content/crime": "Crime",
  "moderated_content/hate": "Hate",
  "moderated_content/profanity": "Profanity",
  "moderated_content/sexual": "Sexual Content",
  "moderated_content/violence": "Violence",
  "moderated_content/weapons": "Weapons",
  "pii/address": "PII: Address",
  "pii/credit_card": "PII: Credit Card",
  "pii/iban_code": "PII: IBAN",
  "pii/ip_address": "PII: IP Address",
  "pii/us_social_security_number": "PII: SSN"
};

