// ponytail: also copied to sidecar/static/app.js
export function answerAskCard(
  kind: "text" | "single" | "multi",
  value: string | string[],
): string {
  return JSON.stringify({ kind, value });
}
