import { FormEvent, useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { useSession } from "../App";
import { api, Row } from "../api";
import FilterBar, { RANGES } from "../components/FilterBar";
import RowDrawer from "../components/RowDrawer";
import { cellText, number } from "../format";

const PAGE_SIZE = 50;

const STATUS_PILL: Record<string, string> = { processed: "good", failed: "critical" };

export default function TableView() {
  const { table: name = "" } = useParams();
  const { tables, refreshTables } = useSession();
  const meta = tables.find((t) => t.name === name);

  // Everything that shapes the list lives in the URL, so links can be shared.
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const page = Number(params.get("page") ?? 0);
  const sort = params.get("sort") ?? "";
  const order = params.get("order") ?? "desc";
  const open = params.get("open");

  // Tagged with its table: the page component is reused across tables, and rows of
  // one table must never be drawn with another table's columns.
  const [result, setResult] = useState<{ table: string; total: number; rows: Row[] } | null>(null);
  const data = result?.table === name ? result : null;
  const [error, setError] = useState("");
  const [search, setSearch] = useState(q);
  const [creating, setCreating] = useState(false);
  const [reload, setReload] = useState(0);
  const [openRow, setOpenRow] = useState<Row | null>(null);

  useEffect(() => setSearch(q), [q, name]);

  const timeColumn = meta?.time_column;
  const query = useMemo(() => {
    const out = new URLSearchParams();
    params.forEach((value, key) => {
      if (key === "q" || key === "sort" || key === "order" || key.startsWith("filter.")) out.append(key, value);
    });
    // "last 24 hours" is relative: turn it into a timestamp now, not when the link was made
    const range = RANGES[params.get("range") ?? ""];
    if (range && timeColumn) out.append(`filter.${timeColumn}__gte`, new Date(Date.now() - range.ms).toISOString());
    out.set("limit", String(PAGE_SIZE));
    out.set("offset", String(page * PAGE_SIZE));
    return out.toString();
  }, [params, page, timeColumn]);

  useEffect(() => {
    let current = true; // a slower, older response must not overwrite a newer one
    setError("");
    api<{ total: number; rows: Row[] }>(`/tables/${name}/rows?${query}`)
      .then((page) => current && setResult({ table: name, ...page }))
      .catch((e) => current && setError(e.message));
    return () => {
      current = false;
    };
  }, [name, query, reload]);

  // A linked row (?open=) may not be on this page: fetch it on its own.
  useEffect(() => {
    let current = true;
    setOpenRow(null);
    if (!open || !meta || !data || data.rows.some((row) => String(row[meta.primary_key]) === open)) return;
    api<Row>(`/tables/${name}/rows/${encodeURIComponent(open)}`)
      .then((row) => current && setOpenRow(row))
      .catch(() => {});
    return () => {
      current = false;
    };
  }, [open, name, meta, data]);

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    setParams(next);
  };

  if (!meta) return <div className="page-body muted">กำลังโหลด…</div>;

  const pk = meta.primary_key;
  const selected = data?.rows.find((row) => String(row[pk]) === open) ?? openRow;
  const from = data && data.total ? page * PAGE_SIZE + 1 : 0;
  const to = data ? Math.min((page + 1) * PAGE_SIZE, data.total) : 0;

  const changed = () => {
    setReload((n) => n + 1);
    refreshTables();
  };

  return (
    <>
      <header className="page-head">
        <h1>{meta.label}</h1>
        <span className="mono muted">{meta.name}</span>
        {!meta.editable && <span className="muted">· อ่านอย่างเดียว</span>}
        <span className="spacer" />
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            update({ q: search.trim(), page: null, open: null });
          }}
        >
          <input
            className="search"
            type="search"
            placeholder="ค้นหาในทุกคอลัมน์ข้อความ แล้วกด Enter"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </form>
        {meta.editable && (
          <button className="primary" onClick={() => setCreating(true)}>
            + เพิ่ม
          </button>
        )}
      </header>

      <div className="page-body">
        <FilterBar meta={meta} params={params} update={update} />

        {error && <p className="error">{error}</p>}

        <div className="table-wrap" style={{ opacity: data ? 1 : 0.5 }}>
          <table className="data">
            <thead>
              <tr>
                {meta.columns.map((column) => {
                  const numeric = column.kind === "integer" || column.kind === "number";
                  const active = sort === column.name;
                  return (
                    <th
                      key={column.name}
                      className={numeric ? "num" : ""}
                      aria-sort={active ? (order === "asc" ? "ascending" : "descending") : "none"}
                      onClick={() =>
                        update({ sort: column.name, order: active && order === "desc" ? "asc" : "desc", page: null })
                      }
                    >
                      {column.name} {active ? (order === "asc" ? "↑" : "↓") : ""}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {data?.rows.map((row) => (
                <tr
                  key={String(row[pk])}
                  className={String(row[pk]) === open ? "selected" : ""}
                  onClick={() => update({ open: String(row[pk]) })}
                >
                  {meta.columns.map((column) => {
                    const value = row[column.name];
                    const numeric = column.kind === "integer" || column.kind === "number";
                    if (column.name === "status" && name === "webhook_events") {
                      return (
                        <td key={column.name}>
                          <span className={`pill ${STATUS_PILL[String(value)] ?? ""}`}>{String(value)}</span>
                        </td>
                      );
                    }
                    return (
                      <td
                        key={column.name}
                        className={`${numeric ? "num" : ""} ${column.primary_key || column.name.endsWith("_id") ? "mono" : ""}`}
                        title={typeof value === "string" ? value : undefined}
                      >
                        {cellText(value, column.kind)}
                      </td>
                    );
                  })}
                </tr>
              ))}
              {data && data.rows.length === 0 && (
                <tr>
                  <td colSpan={meta.columns.length} className="muted" style={{ textAlign: "center", padding: 28 }}>
                    ไม่มีข้อมูล
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="pager">
          <span className="num">
            {number(from)}–{number(to)} จาก {number(data?.total ?? 0)}
          </span>
          <button disabled={page === 0} onClick={() => update({ page: String(page - 1) })}>
            ‹ ก่อนหน้า
          </button>
          <button disabled={!data || to >= data.total} onClick={() => update({ page: String(page + 1) })}>
            ถัดไป ›
          </button>
        </div>
      </div>

      {(selected || creating) && (
        <RowDrawer
          meta={meta}
          row={creating ? null : selected}
          onClose={() => {
            setCreating(false);
            update({ open: null });
          }}
          onChanged={(pkValue) => {
            changed();
            setCreating(false);
            update({ open: pkValue });
          }}
        />
      )}
    </>
  );
}
