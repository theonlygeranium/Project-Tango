// FILE: app-config.ts
import type { AppConfig } from './lib/types';

export const APP_CONFIG_DEFAULTS: AppConfig = {
  companyName: 'Project Tango',
  pageTitle: 'Project Tango | AI Companion',
  pageDescription: 'A voice-first AI companion routed through Schubert.',
  startButtonText: 'Start conversation',

  supportsChatInput: true,
  supportsVideoInput: true,
  supportsScreenShare: true,
  isPreConnectBufferEnabled: true,

  logo: '/logo.svg',
  accent: '#4A90E2',
  logoDark: '/logo-dark.svg',
  accentDark: '#81A1C1',
};
