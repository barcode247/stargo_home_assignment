const ISRAEL = "Asia/Jerusalem";

const dateTime = new Intl.DateTimeFormat("en-GB", {
  timeZone: ISRAEL, weekday: "short", day: "2-digit", month: "short",
  hour: "2-digit", minute: "2-digit", hour12: false,
});

/** Any ISO timestamp shown as Israel time, e.g. "Mon 05 Oct, 13:45". */
export function israelTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return dateTime.format(new Date(iso));
}

/** Current time in Israel as a value for <input type="datetime-local">. */
export function israelNowLocalInput(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: ISRAEL, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).formatToParts(new Date());
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const hour = get("hour") === "24" ? "00" : get("hour");
  return `${get("year")}-${get("month")}-${get("day")}T${hour}:${get("minute")}`;
}

export const channelLabel: Record<string, string> = {
  email_reply: "Email",
  form_fill: "Form",
  linkedin_dm: "LinkedIn",
};
