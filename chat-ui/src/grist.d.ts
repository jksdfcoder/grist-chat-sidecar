export {};

type GristRow = Record<string, unknown>;

declare global {
  interface Window {
    grist?: {
      ready: (opts: unknown) => void;
      onRecords: (
        cb: (records: GristRow[]) => void,
        opts?: { includeColumns?: "shown" | "normal" | "all"; format?: "rows" | "columns"; keepEncoded?: boolean },
      ) => void;
      fetchSelectedTable?: (opts?: {
        keepEncoded?: boolean;
        format?: "rows" | "columns";
        includeColumns?: "shown" | "normal" | "all";
      }) => Promise<GristRow[] | Record<string, unknown[]>>;
      mapColumnNames: (row: GristRow) => GristRow;
      mapColumnNamesBack?: (row: GristRow) => GristRow | null;
      docApi?: {
        applyUserActions: (actions: unknown[][]) => Promise<unknown>;
        fetchTable?: (tableId: string) => Promise<Record<string, unknown[]>>;
      };
      getTable: () => {
        upsert: (recs: unknown, opts?: { add?: boolean; update?: boolean; onMany?: "none" | "first" | "all" }) => Promise<void>;
        getTableId: () => Promise<string>;
      };
    };
  }
}
