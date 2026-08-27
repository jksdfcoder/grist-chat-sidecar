import { describe, expect, it } from "vitest";
import { commitPayload, toggleRejected } from "./hunks";

describe("hunks", () => {
  it("toggles keys and serializes", () => {
    let s = new Set<string>();
    s = toggleRejected(s, "a@hku.hk");
    s = toggleRejected(s, "b@hku.hk");
    s = toggleRejected(s, "a@hku.hk");
    expect(commitPayload(s).rejected_keys).toEqual(["b@hku.hk"]);
  });
});
