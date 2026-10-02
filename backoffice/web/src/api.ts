export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** JSON call to the backoffice API. The session lives in an HttpOnly cookie. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    credentials: "same-origin",
    ...init,
    headers: {
      "X-Requested-With": "backoffice", // the API refuses writes without it (CSRF guard)
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });

  if (response.status === 401 && path !== "/login") {
    window.dispatchEvent(new Event("backoffice:signed-out"));
  }

  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, message);
  }

  return response.status === 204 ? (undefined as T) : response.json();
}

export const send = (method: string, body?: unknown) => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
});

// ---- shapes returned by the API ----

export type Me = { username: string; role: "admin" | "viewer" };

export type ColumnKind = "string" | "text" | "integer" | "number" | "boolean" | "datetime" | "json";

export type Column = {
  name: string;
  kind: ColumnKind;
  nullable: boolean;
  primary_key: boolean;
  generated: boolean;
};

export type TableMeta = {
  name: string;
  label: string;
  editable: boolean;
  rows: number;
  primary_key: string;
  time_column: string | null; // what the time-range picker filters on
  columns: Column[];
};

export type Row = Record<string, unknown>;
