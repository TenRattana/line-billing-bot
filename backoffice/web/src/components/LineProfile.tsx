import { useEffect, useState } from "react";

import { api } from "../api";

type Profile = { display_name: string; picture_url: string | null; status_message: string | null; language: string | null };

/** Live LINE profile of a user id (LINE refuses it if the user blocked the bot). */
export default function LineProfile({ lineUserId }: { lineUserId: string }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true; // the drawer may already show another user
    setProfile(null);
    setError("");
    api<Profile>(`/line/profile/${encodeURIComponent(lineUserId)}`)
      .then((profile) => current && setProfile(profile))
      .catch((e) => current && setError(e.message));
    return () => {
      current = false;
    };
  }, [lineUserId]);

  return (
    <div className="card line-card">
      {profile?.picture_url ? <img src={profile.picture_url} alt="" /> : <img alt="" />}
      <div>
        <div>
          <b>{profile?.display_name ?? (error ? "ไม่มีข้อมูลโปรไฟล์" : "กำลังโหลด…")}</b>
          <span className="muted"> · LINE</span>
        </div>
        <div className="secondary">{error || profile?.status_message || ""}</div>
        <div className="mono muted">{lineUserId}</div>
      </div>
    </div>
  );
}
