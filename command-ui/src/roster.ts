/** Preferred Nexus UI order. Extra API bots append after these. */
export const UI_ROSTER = [
  "admiral",
  "architect",
  "quartermaster",
  "cartographer",
  "voss",
  "proctor",
  "cortex",
  "sentinel",
] as const;

export const ALIAS_IDS = new Set(["dr_voss", "dr-voss"]);

export const ROLE_COLOR: Record<string, string> = {
  coordinator: "#ffd23d",
  developer: "#9b5cff",
  operations: "#4a7fff",
  documentation: "#2ad4a4",
  medical: "#ff4d6a",
  science: "#ff7a1a",
  testing: "#ff4d9e",
};

export function orderedBotIds(bots: Record<string, { meta?: { id?: string } }>): string[] {
  const keys = Object.keys(bots).filter((id) => !ALIAS_IDS.has(id));
  const preferred = UI_ROSTER.filter((id) => keys.includes(id));
  const extra = keys.filter((id) => !UI_ROSTER.includes(id as (typeof UI_ROSTER)[number]));
  return [...preferred, ...extra];
}
