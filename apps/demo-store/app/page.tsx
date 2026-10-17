"use client";
import { useState } from "react";
export default function Store() {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function checkout() {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/checkout", { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail);
      window.location.assign(data.url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Checkout failed");
      setBusy(false);
    }
  }
  return (
    <main>
      <nav>
        <strong>CONEL / OBJECTS</strong>
        <span>DEMO STORE ? TEST MODE</span>
      </nav>
      <section>
        <div className="product">
          <div className="kit">FOCUS.</div>
        </div>
        <div>
          <small>LESS NOISE. MORE INTENTION.</small>
          <h1>
            A little space
            <br />
            to do great work.
          </h1>
          <p>
            The Focus Kit. A considered collection of desk essentials for the
            way you work.
          </p>
          <p style={{ fontSize: 24, color: "#1d2924" }}>
            $49.00 <small>USD</small>
          </p>
          <button disabled={busy} onClick={checkout}>
            {busy ? "Opening checkout?" : "Get the Focus Kit ?"}
          </button>
          {error && (
            <p role="alert" style={{ color: "#a32d2d" }}>
              {error}
            </p>
          )}
          <p>
            <small>Stripe test mode. No real payment is taken.</small>
          </p>
        </div>
      </section>
      <div className="note">
        Connected to CONEL for controlled recovery testing.{" "}
        <a href="/demo-control">Demo controls</a>
      </div>
    </main>
  );
}
