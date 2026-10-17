"use client";
import { useState } from "react";
export default function Controls() {
  const [key, setKey] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  async function act(action: string) {
    setBusy(true);
    try {
      const r = await fetch("/api/demo/" + action, {
        method: "POST",
        headers: { Authorization: "Bearer " + key },
      });
      const d = await r.json();
      setMessage(d.detail ?? d.status);
    } catch {
      setMessage("Request failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="controls">
      <a href="/">CONEL Demo Store</a>
      <h1>Controlled failure.</h1>
      <p>
        Local development only. These controls change the checkout source file.
        The regression test will fail while the bug is active.
      </p>
      <label>
        Admin key
        <input
          type="password"
          autoComplete="off"
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
      </label>
      <button disabled={busy || !key} onClick={() => act("break")}>
        Inject checkout failure
      </button>
      <button disabled={busy || !key} onClick={() => act("reset")}>
        Reset demo
      </button>
      <p role="status">{message}</p>
      <small>The reset is a manual demo reset, not a CONEL repair.</small>
    </main>
  );
}
