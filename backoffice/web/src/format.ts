const bangkok = { timeZone: "Asia/Bangkok" } as const;

export const number = (value: number) => value.toLocaleString("th-TH");

export const baht = (value: number) =>
  value.toLocaleString("th-TH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** 12.9K / 4.2M for stat tiles. */
export const compact = (value: number) =>
  value.toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 1 });

export const dateTime = (iso: string) =>
  new Date(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`).toLocaleString("th-TH", {
    ...bangkok,
    dateStyle: "medium",
    timeStyle: "medium",
  });

export const shortDay = (day: string) =>
  new Date(`${day}T00:00:00+07:00`).toLocaleDateString("th-TH", { ...bangkok, day: "numeric", month: "short" });

/** A cell's text in the data table (full values live in the row drawer). */
export function cellText(value: unknown, kind: string): string {
  if (value === null || value === undefined) return "—";
  if (kind === "boolean") return value ? "✓" : "✗";
  if (kind === "datetime") return dateTime(String(value));
  if (kind === "json") return JSON.stringify(value);
  return String(value);
}
