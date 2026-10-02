import { FormEvent, useState } from "react";

import { api, Me, send } from "../api";

export default function Login({ onSignedIn }: { onSignedIn: (me: Me) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onSignedIn(await api<Me>("/login", send("POST", { username, password })));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <h1>Billing Backoffice</h1>
        <label className="secondary">
          ชื่อผู้ใช้
          <input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} style={{ width: "100%" }} />
        </label>
        <label className="secondary">
          รหัสผ่าน
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} style={{ width: "100%" }} />
        </label>
        {error && <div className="error" role="alert">{error}</div>}
        <button className="primary" disabled={busy || !username || !password}>
          {busy ? "กำลังเข้าสู่ระบบ…" : "เข้าสู่ระบบ"}
        </button>
      </form>
    </div>
  );
}
