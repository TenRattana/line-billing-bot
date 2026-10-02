import { FormEvent, useEffect, useRef, useState } from "react";

import { api, Column, ColumnKind, TableMeta } from "../api";
import { dateTime } from "../format";

/** Time presets for the table's time column; resolved to a timestamp at request time. */
export const RANGES: Record<string, { label: string; ms: number }> = {
  "1h": { label: "1 ชั่วโมง", ms: 3600e3 },
  "24h": { label: "24 ชั่วโมง", ms: 86400e3 },
  "7d": { label: "7 วัน", ms: 7 * 86400e3 },
  "30d": { label: "30 วัน", ms: 30 * 86400e3 },
  "90d": { label: "90 วัน", ms: 90 * 86400e3 },
};

const OP_LABEL: Record<string, string> = {
  eq: "=",
  ne: "≠",
  contains: "มีคำว่า",
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
  isnull: "ว่าง / มีค่า",
};

function operators(kind: ColumnKind): string[] {
  switch (kind) {
    case "boolean":
      return ["eq"];
    case "integer":
    case "number":
      return ["eq", "ne", "gt", "gte", "lt", "lte", "isnull"];
    case "datetime":
      return ["gte", "lte", "isnull"];
    case "json":
      return ["contains", "isnull"];
    default:
      return ["eq", "ne", "contains", "isnull"];
  }
}

const opLabel = (op: string, kind?: ColumnKind) =>
  kind === "datetime" && op === "gte" ? "ตั้งแต่" : kind === "datetime" && op === "lte" ? "ถึง" : OP_LABEL[op];

/** filter.<column>__<op> URL key (a bare column means "eq"). */
const paramKey = (column: string, op: string) => `filter.${column}${op === "eq" ? "" : `__${op}`}`;

type Active = { key: string; column: string; op: string; value: string };

export function activeFilters(params: URLSearchParams): Active[] {
  const out: Active[] = [];
  params.forEach((value, key) => {
    if (!key.startsWith("filter.")) return;
    const [column, op = "eq"] = key.slice("filter.".length).split("__");
    out.push({ key, column, op, value });
  });
  return out;
}

function shownValue(filter: Active, column?: Column) {
  if (filter.op === "isnull") return filter.value === "true" ? "ว่าง" : "มีค่า";
  if (column?.kind === "datetime") return dateTime(filter.value);
  return filter.value;
}

// ---------------------------------------------------------------------------

function AddFilter({ meta, onAdd, onClose }: { meta: TableMeta; onAdd: (key: string, value: string) => void; onClose: () => void }) {
  const [columnName, setColumnName] = useState(meta.columns[0]?.name ?? "");
  const column = meta.columns.find((c) => c.name === columnName)!;
  const ops = operators(column.kind);
  const [op, setOp] = useState(ops[0]);
  const [value, setValue] = useState("");
  const [suggestions, setSuggestions] = useState<{ value: string | boolean; count: number }[]>([]);
  const box = useRef<HTMLFormElement>(null);

  useEffect(() => {
    setOp(operators(column.kind)[0]);
    setValue(column.kind === "boolean" ? "true" : "");
  }, [column.kind, columnName]);

  // Suggest real values from the table (like LangSmith's value picker).
  useEffect(() => {
    if (["json", "datetime", "boolean"].includes(column.kind) || op === "isnull") return setSuggestions([]);
    let current = true;
    const timer = setTimeout(() => {
      api<{ value: string; count: number }[]>(
        `/tables/${meta.name}/values/${encodeURIComponent(columnName)}?q=${encodeURIComponent(value)}`,
      )
        .then((rows) => current && setSuggestions(rows))
        .catch(() => {});
    }, 200);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [meta.name, columnName, column.kind, op, value]);

  useEffect(() => {
    const outside = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && onClose();
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [onClose]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    let final = op === "isnull" ? value || "true" : value.trim();
    if (column.kind === "datetime" && op !== "isnull" && final) {
      final = new Date(`${final}:00+07:00`).toISOString(); // the picker is in Bangkok time
    }
    if (!final) return;
    onAdd(paramKey(columnName, op), final);
  };

  const listId = `values-${meta.name}-${columnName}`;

  return (
    <form ref={box} className="popover" onSubmit={submit}>
      <label>
        คอลัมน์
        <select value={columnName} onChange={(e) => setColumnName(e.target.value)} autoFocus>
          {meta.columns.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        เงื่อนไข
        <select value={op} onChange={(e) => setOp(e.target.value)}>
          {ops.map((o) => (
            <option key={o} value={o}>
              {opLabel(o, column.kind)}
            </option>
          ))}
        </select>
      </label>
      <label>
        ค่า
        {op === "isnull" ? (
          <select value={value || "true"} onChange={(e) => setValue(e.target.value)}>
            <option value="true">ว่าง</option>
            <option value="false">มีค่า</option>
          </select>
        ) : column.kind === "boolean" ? (
          <select value={value} onChange={(e) => setValue(e.target.value)}>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        ) : column.kind === "datetime" ? (
          <input type="datetime-local" value={value} onChange={(e) => setValue(e.target.value)} required />
        ) : (
          <>
            <input
              value={value}
              list={listId}
              onChange={(e) => setValue(e.target.value)}
              inputMode={column.kind === "integer" || column.kind === "number" ? "decimal" : undefined}
              placeholder="พิมพ์หรือเลือกจากรายการ"
              required
            />
            <datalist id={listId}>
              {suggestions.map((s) => (
                <option key={String(s.value)} value={String(s.value)}>
                  {`${s.count} แถว`}
                </option>
              ))}
            </datalist>
          </>
        )}
      </label>
      <div className="popover-actions">
        <button type="button" className="ghost" onClick={onClose}>
          ยกเลิก
        </button>
        <button className="primary">เพิ่ม filter</button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------

export default function FilterBar({
  meta,
  params,
  update,
}: {
  meta: TableMeta;
  params: URLSearchParams;
  update: (changes: Record<string, string | null>) => void;
}) {
  const [adding, setAdding] = useState(false);
  const filters = activeFilters(params);
  const range = params.get("range") ?? "";

  const clearAll = () => update({ range: null, page: null, ...Object.fromEntries(filters.map((f) => [f.key, null])) });

  return (
    <div className="filter-bar">
      {meta.time_column && (
        <select
          className="range"
          value={range}
          aria-label={`ช่วงเวลาของ ${meta.time_column}`}
          onChange={(e) => update({ range: e.target.value || null, page: null })}
        >
          <option value="">ทุกช่วงเวลา</option>
          {Object.entries(RANGES).map(([key, r]) => (
            <option key={key} value={key}>
              {r.label}ล่าสุด
            </option>
          ))}
        </select>
      )}

      {filters.map((f) => {
        const column = meta.columns.find((c) => c.name === f.column);
        return (
          <span key={f.key} className="filter-chip">
            <span className="mono">{f.column}</span>
            <span className="muted">{opLabel(f.op, column?.kind)}</span>
            <b>{shownValue(f, column)}</b>
            <button className="ghost" aria-label={`ลบ filter ${f.column}`} onClick={() => update({ [f.key]: null, page: null })}>
              ✕
            </button>
          </span>
        );
      })}

      <span className="popover-anchor">
        <button onClick={() => setAdding((open) => !open)}>+ Filter</button>
        {adding && (
          <AddFilter
            meta={meta}
            onClose={() => setAdding(false)}
            onAdd={(key, value) => {
              update({ [key]: value, page: null });
              setAdding(false);
            }}
          />
        )}
      </span>

      {(filters.length > 0 || range) && (
        <button className="ghost" onClick={clearAll}>
          ล้าง filter ทั้งหมด
        </button>
      )}
    </div>
  );
}
