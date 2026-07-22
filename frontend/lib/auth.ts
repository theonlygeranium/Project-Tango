import type { LlmModelId } from '@/lib/llm-models';

export type UserRole = 'admin' | 'regular';

export interface PersonaAccessPolicy {
  persona_id: string;
  llm_model_override: LlmModelId | null;
  effective_llm_model?: LlmModelId;
}

export interface CurrentUser {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  role: UserRole;
  persona_access: PersonaAccessPolicy[];
}

export interface AdminUser extends CurrentUser {
  is_active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  last_login_at?: string | null;
}

export interface AuthSessionResponse {
  user: CurrentUser;
}

export interface AdminUsersResponse {
  users: AdminUser[];
}

export interface GeneratedPasswordResponse {
  generated_password: string;
  user?: AdminUser;
  user_id?: string;
}

export interface BackendPersona {
  id: string;
  label: string;
  display_name: string;
  role_description: string;
  llm_model: LlmModelId;
  llm_model_override?: LlmModelId | null;
  effective_llm_model?: LlmModelId;
  stt_language?: string;
  tts_backend?: string;
}

export interface BackendLlmModel {
  id: LlmModelId;
  label: string;
}

export interface PersonaCatalogResponse {
  default_persona_id: string;
  personas: BackendPersona[];
  llm_models: BackendLlmModel[];
}

export interface UserMutationPayload {
  first_name: string;
  last_name: string;
  email: string;
  persona_access: Array<{
    persona_id: string;
    llm_model_override: LlmModelId | null;
  }>;
}

export function userDisplayName(user: Pick<CurrentUser, 'first_name' | 'last_name'>) {
  return `${user.first_name} ${user.last_name}`.trim();
}

export function userInitials(user: Pick<CurrentUser, 'first_name' | 'last_name'>) {
  return `${user.first_name.charAt(0)}${user.last_name.charAt(0)}`.toUpperCase() || 'TU';
}
