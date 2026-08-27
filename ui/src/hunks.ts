// ponytail: also copied to sidecar/static/app.js
export function toggleRejected(rejected: Set<string>, key: string): Set<string> {
  if (rejected.has(key)) rejected.delete(key);
  else rejected.add(key);
  return rejected;
}

export function commitPayload(rejected: Set<string>): { rejected_keys: string[] } {
  return { rejected_keys: [...rejected] };
}
