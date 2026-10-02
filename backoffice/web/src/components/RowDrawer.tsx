import { useEffect, useState } from "react";

import { useSession } from "../App";
import { api, Column, Row, send, TableMeta } from "../api";
import { cellText } from "../format";
import LineProfile from "./LineProfile";
import SlipFiles from "./SlipFiles";

type Props = {
  meta: TableMeta;
  row: Row | null; // null = creating a new row
  onClose: () => void;
  onChanged: (pk: string | null) => void; // null after a delete
};

/** Form text for a value; parsed back per column kind on save. */
function toText(value: unknown, column: Column): string {
  if (value === null || value === undefined) return "";
  if (column.kind === "json") return JSON.stringify(value, null, 2);
  return String(value);
}

function fromText(text: string, column: Column): unknown {
  if (text === "") return null;
  if (column.kind === "boolean") return text === "true";
  if (column.kind === "json") return JSON.parse(text); // SyntaxError -> shown to the user
  return text; // the API coerces numbers / dates and rejects nonsense with a message
}

function lineUserIdOf(table: string, row: Row | null): string | null {
  if (!row) return null;
  if (table === "user_identities") return row.provider === "line" ? String(row.external_id) : null;
  return typeof row.line_user_id === "string" ? row.line_user_id : null;
}

export default function RowDrawer({ meta, row, onClose, onChanged }: Props) {
  const { me } = useSession();
  const creating = row === null;
  const [editing, setEditing] = useState(creating);
  const [tab, setTab] = useState<"fields" | "json">("fields");
  const [form, setForm] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const pk = row ? String(row[meta.primary_key]) : "";
  const columns = meta.columns.filter((c) => !(creating && c.generated));
  const lineUserId = lineUserIdOf(meta.name, row);

  useEffect(() => {
    setForm(Object.fromEntries(meta.columns.map((c) => [c.name, toText(row?.[c.name], c)])));
    setEditing(row === null);
    setError("");
  }, [row, meta]);

  useEffect(() => {
    // Esc closes an open image viewer first (it handles its own Esc), not the drawer behind it.
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !document.querySelector("dialog[open]") && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const save = () =>
    run(async () => {
      const body: Row = {};
      for (const column of columns) {
        const text = form[column.name] ?? "";
        if (creating ? text !== "" : text !== toText(row?.[column.name], column)) {
          body[column.name] = fromText(text, column);
        }
      }
      if (creating) {
        const created = await api<Row>(`/tables/${meta.name}/rows`, send("POST", body));
        onChanged(String(created[meta.primary_key]));
      } else {
        await api(`/tables/${meta.name}/rows/${encodeURIComponent(pk)}`, send("PATCH", body));
        setEditing(false);
        onChanged(pk);
      }
    });

  const remove = () => {
    if (!window.confirm(`ลบแถว ${pk} ออกจาก ${meta.name}? ย้อนกลับไม่ได้ (มีบันทึกใน audit log)`)) return;
    run(async () => {
      await api(`/tables/${meta.name}/rows/${encodeURIComponent(pk)}`, send("DELETE"));
      onChanged(null);
    });
  };

  const release = () => {
    const empCode = String(row?.emp_code);
    if (!window.confirm(`ปลดการผูก LINE ของรหัส ${empCode}? พนักงานต้องลงทะเบียนใหม่`)) return;
    run(async () => {
      await api(`/line/release/${encodeURIComponent(empCode)}`, send("POST"));
      onChanged(null);
    });
  };

  const input = (column: Column) => {
    const value = form[column.name] ?? "";
    const set = (text: string) => setForm({ ...form, [column.name]: text });
    // The key identifies the row; DB-stamped times (create_at, update_at) aren't hand-edited.
    const locked = !creating && (column.primary_key || (column.generated && column.kind === "datetime"));

    if (column.kind === "boolean") {
      return (
        <select value={value} onChange={(e) => set(e.target.value)}>
          {column.nullable && <option value="">—</option>}
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      );
    }
    if (column.kind === "json" || column.kind === "text") {
      return <textarea value={value} onChange={(e) => set(e.target.value)} />;
    }
    return (
      <input
        value={value}
        disabled={locked}
        placeholder={column.kind === "datetime" ? "2026-09-29T10:00:00+07:00" : column.nullable ? "ว่างได้" : ""}
        inputMode={column.kind === "integer" || column.kind === "number" ? "decimal" : undefined}
        onChange={(e) => set(e.target.value)}
      />
    );
  };

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="รายละเอียดแถว">
        <div className="drawer-head">
          <h2>{creating ? `เพิ่ม ${meta.label}` : meta.label}</h2>
          {!creating && <span className="mono muted">{pk}</span>}
          <span className="spacer" />
          <button className="ghost" onClick={onClose} aria-label="ปิด">
            ✕
          </button>
        </div>

        <div className="drawer-body">
          {lineUserId && <LineProfile lineUserId={lineUserId} />}
          {meta.name === "bill_sends" && !creating && <SlipFiles sendId={pk} />}

          {!creating && (
            <div className="tabs">
              <button className={tab === "fields" ? "on" : ""} onClick={() => setTab("fields")}>
                ข้อมูล
              </button>
              <button className={tab === "json" ? "on" : ""} onClick={() => setTab("json")}>
                JSON
              </button>
            </div>
          )}

          {tab === "json" && !creating ? (
            <pre className="json">{JSON.stringify(row, null, 2)}</pre>
          ) : (
            <dl className="fields">
              {columns.map((column) => (
                <div key={column.name} style={{ display: "contents" }}>
                  <dt className="mono">
                    {column.name}
                    {!column.nullable && editing && !column.generated ? " *" : ""}
                  </dt>
                  <dd>
                    {editing ? (
                      input(column)
                    ) : column.kind === "json" || column.name === "error" ? (
                      row?.[column.name] == null ? (
                        "—"
                      ) : (
                        <pre className="json">
                          {column.kind === "json" ? JSON.stringify(row[column.name], null, 2) : String(row[column.name])}
                        </pre>
                      )
                    ) : (
                      cellText(row?.[column.name], column.kind)
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          )}

          {error && <div className="error" role="alert">{error}</div>}
        </div>

        {meta.editable && (
          <div className="drawer-foot">
            {editing ? (
              <>
                <button className="primary" onClick={save} disabled={busy}>
                  {busy ? "กำลังบันทึก…" : "บันทึก"}
                </button>
                <button onClick={() => (creating ? onClose() : setEditing(false))} disabled={busy}>
                  ยกเลิก
                </button>
              </>
            ) : (
              <>
                <button onClick={() => setEditing(true)}>แก้ไข</button>
                {meta.name === "user_identities" && lineUserId && me.role === "admin" && (
                  <button onClick={release} disabled={busy}>
                    ปลดการผูก LINE
                  </button>
                )}
                <span className="spacer" />
                <button className="danger" onClick={remove} disabled={busy}>
                  ลบ
                </button>
              </>
            )}
          </div>
        )}
      </aside>
    </>
  );
}
