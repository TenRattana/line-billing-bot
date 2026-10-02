import { ReactNode, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  TooltipProps,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../api";
import { baht, compact, dateTime, number, shortDay } from "../format";

type Dashboard = {
  days: number;
  totals: {
    employees: number;
    bound_line_accounts: number;
    sends: number;
    sent_amount: number;
    events: number;
    failed_events: number;
    rejected_registrations: number;
  };
  events_by_day: { day: string; processed: number; skipped: number; failed: number }[];
  sends_by_day: { day: string; count: number; amount: number }[];
  top_employees: { emp_code: string; name: string | null; sends: number; amount: number }[];
  rejected_by_reason: Record<string, number>;
  recent_failures: { id: number; received_at: string; event_type: string; line_user_id: string | null; error: string }[];
};

type Followers = { date: string; status: string; followers?: number; blocks?: number };

const RANGES = [7, 30, 90];

const REASONS: Record<string, string> = {
  code_not_found: "ไม่พบรหัส",
  name_mismatch: "ชื่อไม่ตรง",
  code_already_bound: "รหัสผูก LINE อื่นแล้ว",
  employee_inactive: "พนักงานปิดใช้งาน",
  reverify_code_mismatch: "ยืนยันซ้ำด้วยรหัสผิด",
};

// Series: processed = slot 1, skipped = neutral, failed = the reserved critical status color.
const EVENT_SERIES = [
  { key: "processed", label: "สำเร็จ", color: "var(--series-1)" },
  { key: "skipped", label: "ข้าม", color: "var(--neutral-mark)" },
  { key: "failed", label: "ล้มเหลว", color: "var(--critical)" },
] as const;

const axis = { stroke: "var(--axis)", tick: { fill: "var(--text-muted)", fontSize: 12 }, tickLine: false };

function ChartTooltip({ active, payload, label, rows }: TooltipProps<number, string> & {
  rows: (point: Record<string, number>) => { key: string; label: string; value: string; color: string }[];
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload as Record<string, number>;
  return (
    <div className="tooltip">
      <div className="t-head">{shortDay(String(label))}</div>
      {rows(point).map((row) => (
        <div key={row.key} className="t-row">
          <span className="t-key" style={{ background: row.color }} />
          <b>{row.value}</b> <span className="secondary">{row.label}</span>
        </div>
      ))}
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: ReactNode }) {
  return (
    <div className="card tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

function BarList({ rows, empty }: { rows: { key: string; label: ReactNode; value: number; text: string }[]; empty: string }) {
  const max = Math.max(1, ...rows.map((row) => row.value));
  if (!rows.length) return <div className="muted">{empty}</div>;
  return (
    <div className="bars">
      {rows.map((row) => (
        <div key={row.key} className="bar-row">
          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.label}</div>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${(row.value / max) * 100}%` }} />
          </div>
          <div className="num secondary">{row.text}</div>
        </div>
      ))}
    </div>
  );
}

function FollowerLine({ data, dataKey, title, color }: { data: Followers[]; dataKey: "followers" | "blocks"; title: string; color: string }) {
  const last = [...data].reverse().find((row) => row[dataKey] !== undefined);
  return (
    <div className="card">
      <div className="chart-title">
        {title} <span className="secondary num">{last?.[dataKey] !== undefined ? number(last[dataKey]!) : "—"}</span>
      </div>
      <div className="chart-sub">รายวันจาก LINE Insight (ข้อมูลถึงเมื่อวาน)</div>
      <ResponsiveContainer width="100%" height={160}>
        <LineChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="date" {...axis} tickFormatter={shortDay} minTickGap={24} />
          <YAxis {...axis} width={44} allowDecimals={false} domain={["auto", "auto"]} />
          <Tooltip
            cursor={{ stroke: "var(--axis)" }}
            content={
              <ChartTooltip
                rows={(p) => [{ key: dataKey, label: title, value: p[dataKey] === undefined ? "ยังไม่มีข้อมูล" : number(p[dataKey]), color }]}
              />
            }
          />
          <Line
            type="monotone"
            dataKey={dataKey}
            stroke={color}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function DashboardPage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<Dashboard | null>(null);
  const [followers, setFollowers] = useState<Followers[] | null>(null);
  const [followersError, setFollowersError] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true; // switching ranges fast: only the latest range may land
    setLoading(true);
    api<Dashboard>(`/dashboard?days=${days}`)
      .then((result) => {
        if (!current) return;
        setData(result);
        setError("");
      })
      .catch((e) => current && setError(e.message))
      .finally(() => current && setLoading(false));
    return () => {
      current = false;
    };
  }, [days]);

  useEffect(() => {
    // LINE Insight keeps at most ~60 days reachable here; beyond that the API caps it.
    let current = true;
    api<Followers[]>(`/line/followers?days=${Math.min(days, 60)}`)
      .then((rows) => {
        if (current) setFollowers(rows.map((row) => (row.status === "ready" ? row : { ...row, followers: undefined, blocks: undefined })));
      })
      .catch((e) => current && setFollowersError(e.message));
    return () => {
      current = false;
    };
  }, [days]);

  const t = data?.totals;

  return (
    <>
      <header className="page-head">
        <h1>Dashboard</h1>
        <span className="spacer" />
        <div className="seg" role="group" aria-label="ช่วงเวลา">
          {RANGES.map((range) => (
            <button key={range} className={range === days ? "on" : ""} onClick={() => setDays(range)}>
              {range} วัน
            </button>
          ))}
        </div>
      </header>

      <div className="page-body" style={{ opacity: loading && data ? 0.6 : 1, transition: "opacity .15s" }}>
        {error && <p className="error">{error}</p>}
        {t && data && (
          <>
            <div className="tiles">
              <Tile label="พนักงานในระบบ" value={number(t.employees)} sub={`ผูก LINE แล้ว ${number(t.bound_line_accounts)} คน`} />
              <Tile label={`ส่งบิล (${days} วัน)`} value={number(t.sends)} sub={`รวม ${baht(t.sent_amount)} บาท`} />
              <Tile label={`Webhook events (${days} วัน)`} value={compact(t.events)} sub={
                t.failed_events ? (
                  <Link to="/data/webhook_events?filter.status=failed" className="pill critical">ล้มเหลว {number(t.failed_events)}</Link>
                ) : (
                  <span className="pill good">ไม่มีที่ล้มเหลว</span>
                )
              } />
              <Tile label={`ลงทะเบียนถูกปฏิเสธ (${days} วัน)`} value={number(t.rejected_registrations)} sub="ดูเหตุผลด้านล่าง" />
            </div>

            <div className="grid-2">
              <div className="card">
                <div className="chart-title">Webhook events ต่อวัน</div>
                <div className="chart-sub">
                  ทุก event ที่ LINE ส่งมา · <Link to="/data/webhook_events">ดูเป็นตาราง</Link>
                </div>
                <div className="legend">
                  {EVENT_SERIES.map((s) => (
                    <span key={s.key}><i style={{ background: s.color }} />{s.label}</span>
                  ))}
                </div>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={data.events_by_day} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
                    <CartesianGrid vertical={false} stroke="var(--grid)" />
                    <XAxis dataKey="day" {...axis} tickFormatter={shortDay} minTickGap={20} />
                    <YAxis {...axis} width={40} allowDecimals={false} />
                    <Tooltip
                      cursor={{ fill: "var(--hover)" }}
                      content={
                        <ChartTooltip
                          rows={(p) => EVENT_SERIES.map((s) => ({ key: s.key, label: s.label, value: number(p[s.key] ?? 0), color: s.color }))}
                        />
                      }
                    />
                    {EVENT_SERIES.map((s, index) => (
                      <Bar
                        key={s.key}
                        dataKey={s.key}
                        stackId="events"
                        fill={s.color}
                        maxBarSize={24}
                        stroke="var(--surface)"
                        strokeWidth={2}
                        radius={index === EVENT_SERIES.length - 1 ? [4, 4, 0, 0] : 0}
                      />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="card">
                <div className="chart-title">ส่งบิลต่อวัน</div>
                <div className="chart-sub">
                  จำนวนบิลที่ยืนยันส่ง · <Link to="/data/bill_sends">ดูเป็นตาราง</Link>
                </div>
                <ResponsiveContainer width="100%" height={244}>
                  <BarChart data={data.sends_by_day} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
                    <CartesianGrid vertical={false} stroke="var(--grid)" />
                    <XAxis dataKey="day" {...axis} tickFormatter={shortDay} minTickGap={20} />
                    <YAxis {...axis} width={40} allowDecimals={false} />
                    <Tooltip
                      cursor={{ fill: "var(--hover)" }}
                      content={
                        <ChartTooltip
                          rows={(p) => [
                            { key: "count", label: "บิล", value: number(p.count), color: "var(--series-1)" },
                            { key: "amount", label: "บาท", value: baht(p.amount), color: "transparent" },
                          ]}
                        />
                      }
                    />
                    <Bar dataKey="count" fill="var(--series-1)" maxBarSize={24} radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="grid-2">
              {followers ? (
                <>
                  <FollowerLine data={followers} dataKey="followers" title="เพื่อนของบอท" color="var(--series-1)" />
                  <FollowerLine data={followers} dataKey="blocks" title="บล็อกบอท" color="var(--series-2)" />
                </>
              ) : (
                <div className="card notice">{followersError ? `LINE Insight: ${followersError}` : "กำลังโหลดข้อมูลจาก LINE…"}</div>
              )}
            </div>

            <div className="grid-2">
              <div className="card">
                <div className="chart-title">พนักงานที่ส่งบิลมากที่สุด</div>
                <div className="chart-sub">{days} วันล่าสุด</div>
                <BarList
                  empty="ยังไม่มีการส่งบิล"
                  rows={data.top_employees.map((e) => ({
                    key: e.emp_code,
                    label: (
                      <>
                        {e.name ?? "—"} <span className="mono muted">{e.emp_code}</span>
                      </>
                    ),
                    value: e.sends,
                    text: `${number(e.sends)} บิล · ${compact(e.amount)}`,
                  }))}
                />
              </div>
              <div className="card">
                <div className="chart-title">เหตุผลที่ลงทะเบียนไม่ผ่าน</div>
                <div className="chart-sub">
                  {days} วันล่าสุด · <Link to="/data/audit_logs?q=employee.rejected">ดูรายการ</Link>
                </div>
                <BarList
                  empty="ไม่มีการลงทะเบียนที่ถูกปฏิเสธ"
                  rows={Object.entries(data.rejected_by_reason).map(([reason, count]) => ({
                    key: reason,
                    label: REASONS[reason] ?? reason,
                    value: count,
                    text: number(count),
                  }))}
                />
              </div>
            </div>

            <div className="card">
              <div className="chart-title">Event ที่ล้มเหลวล่าสุด</div>
              <div className="chart-sub">คลิกเพื่อดู payload และ traceback</div>
              {data.recent_failures.length === 0 ? (
                <div className="muted">ไม่มี</div>
              ) : (
                <table className="data">
                  <tbody>
                    {data.recent_failures.map((f) => (
                      <tr key={f.id}>
                        <td className="num">{dateTime(f.received_at)}</td>
                        <td>{f.event_type}</td>
                        <td className="mono">{f.line_user_id ?? "—"}</td>
                        <td>
                          <Link to={`/data/webhook_events?filter.status=failed&open=${f.id}`} className="pill critical">
                            {f.error || "error"}
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
      </div>
    </>
  );
}
