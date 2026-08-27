import { describe, expect, it } from "vitest";
import { collapseByKeys, isGristColId, missingColumns, placeholderKeys, remapCols, sheetBinds, sheetColumns, sqlNoteText, tableToRows, upsertRecords } from "./gristSheet";

describe("sheetColumns / sheetBinds", () => {
  it("names skip id; binds collect every nonempty col", () => {
    const rows = [
      { id: 1, manualSort: 1, Email: "a@hku.hk", RP_no: "rp00402" },
      { id: 2, Email: "", RP_no: "rp00001" },
    ];
    expect(sheetColumns(rows).sort()).toEqual(["Email", "RP_no"]);
    expect(sheetBinds(rows)).toEqual({
      Email: ["a@hku.hk"],
      RP_no: ["rp00402", "rp00001"],
    });
  });
  it("returns empty object when nothing selected", () => {
    expect(sheetBinds([])).toEqual({});
  });
  it("dedupes bind values and require keys", () => {
    expect(sheetBinds([{ RP_no: "rp00402" }, { RP_no: "rp00402" }])).toEqual({ RP_no: ["rp00402"] });
    expect(sheetBinds([{ Email: "a@hku.hk", RP_no: "rp1" }], ["RP_no"])).toEqual({ RP_no: ["rp1"] });
    expect(tableToRows({ id: [1, 2], RP_no: ["a", "b"] })).toEqual([
      { id: 1, RP_no: "a" },
      { id: 2, RP_no: "b" },
    ]);
    expect(upsertRecords([{ RP_no: "a", Name: "1" }, { RP_no: "a", Name: "2" }], undefined, ["RP_no"])).toEqual([
      { require: { RP_no: "a" }, fields: { RP_no: "a", Name: "1" } },
    ]);
  });
});

describe("placeholderKeys", () => {
  it("extracts lookup cols from SQL", () => {
    expect(placeholderKeys('WHERE crisid IN ({{RP_no}}) AND x IN ({{Email}})')).toEqual(["RP_no", "Email"]);
  });
  it("note is input/output col names", () => {
    expect(sqlNoteText('SELECT v.crisid AS "RP_no", v.fullname AS "Name" WHERE v.crisid IN ({{RP_no}})')).toBe(
      "Input: RP_no\nOutput: Name",
    );
  });
});

describe("upsertRecords", () => {
  it("requires listed keys and drops id", () => {
    const recs = upsertRecords(
      [{ id: 99, "?column?": "nope", RP_no: "rp00402", Email: "a@hku.hk", Name: "A" }],
      (row) => ({ id: row.id, "?column?": row["?column?"], RP_no: row.RP_no, Email: row.Email, Name: row.Name }),
      ["RP_no"],
    );
    expect(recs).toEqual([
      {
        require: { RP_no: "rp00402" },
        fields: { RP_no: "rp00402", Email: "a@hku.hk", Name: "A" },
      },
    ]);
  });
  it("does not require Name/Email when lookup is RP_no", () => {
    const recs = upsertRecords(
      [{ RP_no: "rp00402", Email: "new@hku.hk", Name: "New" }],
      undefined,
      placeholderKeys("WHERE crisid IN ({{RP_no}})"),
    );
    expect(recs[0].require).toEqual({ RP_no: "rp00402" });
    expect(recs[0].fields.Email).toBe("new@hku.hk");
  });
  it("skips rows that lack the lookup key", () => {
    expect(upsertRecords([{ Email: "a@hku.hk", Name: "A" }], undefined, ["RP_no"])).toEqual([]);
  });
  it("flattens array Email so Grist gets text", () => {
    const recs = upsertRecords(
      [{ RP_no: "rp1", Email: ["a@hku.hk", "b@hku.hk"], Name: "A" }],
      undefined,
      ["RP_no"],
    );
    expect(recs[0].fields.Email).toBe("a@hku.hk");
  });
});

describe("remapCols", () => {
  it("folds aliases onto existing sheet cols; keeps new ones", () => {
    expect(
      remapCols([{ name: "A", email: "a@hku.hk", department: "Law", RP_no: "rp1" }], ["Name", "Email", "RP_no"]),
    ).toEqual([{ Name: "A", Email: "a@hku.hk", department: "Law", RP_no: "rp1" }]);
  });
});

describe("collapseByKeys", () => {
  it("one row per RP; prefers campus email; joins depts", () => {
    expect(
      collapseByKeys(
        [
          { RP_no: "rp1", Name: "A", department: '{"Dept A"}', Email: "a@hkucc.hku.hk" },
          { RP_no: "rp1", Name: "A", department: '{"Dept B"}', Email: "a@hku.hk" },
        ],
        ["RP_no"],
      ),
    ).toEqual([{ RP_no: "rp1", Name: "A", department: "Dept A; Dept B", Email: "a@hku.hk" }]);
  });
});

describe("missingColumns", () => {
  it("returns new grist-safe ids", () => {
    expect(missingColumns(["Email", "RP_no"], ["Email", "Faculty", "id", "bad-name"])).toEqual(["Faculty"]);
    expect(missingColumns(["department"], ["Department", "Email"])).toEqual(["Email"]);
    expect(isGristColId("Faculty")).toBe(true);
    expect(isGristColId("bad-name")).toBe(false);
  });
});
