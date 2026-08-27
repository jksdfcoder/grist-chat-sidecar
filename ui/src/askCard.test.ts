import { describe, expect, it } from "vitest";
import { answerAskCard } from "./askCard";

describe("askCard", () => {
  it("joins multi answers", () => {
    expect(JSON.parse(answerAskCard("multi", ["staff", "scopus"]))).toEqual({
      kind: "multi",
      value: ["staff", "scopus"],
    });
  });
});
