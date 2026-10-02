import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes } from "react-router-dom";

import { api, Me, send, TableMeta } from "./api";
import { number } from "./format";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import TableView from "./pages/TableView";

type Session = {
  me: Me;
  tables: TableMeta[];
  refreshTables: () => void;
};

const SessionContext = createContext<Session | null>(null);

export const useSession = () => useContext(SessionContext)!;

export default function App() {
  // undefined = still checking the cookie; null = signed out
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [tables, setTables] = useState<TableMeta[]>([]);

  const refreshTables = useCallback(() => {
    api<TableMeta[]>("/tables").then(setTables).catch(() => {});
  }, []);

  useEffect(() => {
    api<Me>("/me").then(setMe).catch(() => setMe(null));
    const signedOut = () => setMe(null);
    window.addEventListener("backoffice:signed-out", signedOut);
    return () => window.removeEventListener("backoffice:signed-out", signedOut);
  }, []);

  useEffect(() => {
    if (me) refreshTables();
  }, [me, refreshTables]);

  if (me === undefined) return null;
  if (me === null) return <Login onSignedIn={setMe} />;

  const signOut = async () => {
    await api("/logout", send("POST")).catch(() => {});
    setMe(null);
  };

  return (
    <SessionContext.Provider value={{ me, tables, refreshTables }}>
      <div className="shell">
        <nav className="sidebar" aria-label="เมนูหลัก">
          <div className="brand">
            <span className="brand-dot" /> Billing Backoffice
          </div>
          <NavLink to="/" end className="nav-link">
            Dashboard
          </NavLink>

          <div className="nav-section">ข้อมูล</div>
          {tables.map((table) => (
            <NavLink key={table.name} to={`/data/${table.name}`} className="nav-link">
              <span>{table.label}</span>
              <span className="nav-count">{number(table.rows)}</span>
            </NavLink>
          ))}

          <div className="nav-section">ทางลัด</div>
          {/* A plain link: NavLink ignores the query, so it would light up with "Webhook events" */}
          <Link to="/data/webhook_events?filter.status=failed" className="nav-link">
            Event ที่ล้มเหลว
          </Link>

          <div className="sidebar-foot">
            <div>
              <b>{me.username}</b> <span className="muted">· {me.role === "admin" ? "ผู้ดูแล" : "ดูอย่างเดียว"}</span>
            </div>
            <button onClick={signOut}>ออกจากระบบ</button>
          </div>
        </nav>

        <main className="main">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/data/:table" element={<TableView />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </SessionContext.Provider>
  );
}
