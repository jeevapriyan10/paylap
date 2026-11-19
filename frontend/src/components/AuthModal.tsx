import React, { useState } from "react";
import { PayLapClient } from "../api/client";

export interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onLoginSuccess: (user: any) => void;
}

export const AuthModal: React.FC<AuthModalProps> = ({ isOpen, onClose, onLoginSuccess }) => {
  const [tab, setTab] = useState<"login" | "apikey">("login");
  const [email, setEmail] = useState("dev@paylap.local");
  const [password, setPassword] = useState("Development1234!");
  const [apiKey, setApiKey] = useState("pl_test_devkey00000000_1234567890abcdef1234567890abcdef");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleLogin = async (e?: React.FormEvent, customEmail?: string, customPass?: string) => {
    if (e) e.preventDefault();
    const loginEmail = (customEmail ?? email).trim();
    const loginPass = customPass ?? password;

    try {
      setLoading(true);
      setError(null);
      const res = await PayLapClient.post<any>("/v1/auth/login", {
        email: loginEmail,
        password: loginPass,
      });

      if (res.csrf_token) {
        localStorage.setItem("paylap_csrf_token", res.csrf_token);
      }
      localStorage.setItem("paylap_user", JSON.stringify(res.user));
      onLoginSuccess(res.user);
      onClose();
    } catch (err: any) {
      setError(err?.message || "Invalid email or password");
    } finally {
      setLoading(false);
    }
  };

  const handleSaveApiKey = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!apiKey.trim()) {
      setError("Please enter a valid API key.");
      return;
    }
    localStorage.setItem("paylap_api_key", apiKey.trim());
    onLoginSuccess({ email: "API Key User", isApiKey: true });
    onClose();
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: "460px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <h2 style={{ fontSize: "1.2rem", fontWeight: 700, letterSpacing: "-0.01em" }}>Authentication</h2>
          <button className="btn btn-secondary btn-sm" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1.25rem", borderBottom: "1px solid var(--border-subtle)", paddingBottom: "0.5rem" }}>
          <button
            className={`nav-link ${tab === "login" ? "active" : ""}`}
            onClick={() => { setTab("login"); setError(null); }}
          >
            Session Login
          </button>
          <button
            className={`nav-link ${tab === "apikey" ? "active" : ""}`}
            onClick={() => { setTab("apikey"); setError(null); }}
          >
            API Key
          </button>
        </div>

        {tab === "login" ? (
          <form onSubmit={(e) => handleLogin(e)}>
            <div
              style={{
                padding: "0.85rem",
                borderRadius: "var(--radius-sm)",
                backgroundColor: "var(--accent-cyan-bg)",
                border: "1px solid rgba(56, 189, 248, 0.2)",
                marginBottom: "1.25rem",
                fontSize: "0.825rem",
              }}
            >
              <div style={{ fontWeight: 600, color: "var(--accent-cyan)", marginBottom: "0.25rem" }}>
                Development Account
              </div>
              <div style={{ color: "var(--text-secondary)", marginBottom: "0.6rem" }}>
                Pre-filled with seeded dev credentials (<code className="mono">dev@paylap.local</code>).
              </div>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                style={{ width: "100%", justifyContent: "center" }}
                disabled={loading}
                onClick={() => handleLogin(undefined, "dev@paylap.local", "Development1234!")}
              >
                {loading ? "Authenticating..." : "1-Click Sign In as Dev"}
              </button>
            </div>

            <div className="form-group">
              <label className="form-label">EMAIL ADDRESS</label>
              <input
                type="text"
                className="form-input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">PASSWORD</label>
              <input
                type="password"
                className="form-input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>

            {error && (
              <div style={{ color: "var(--accent-rose)", fontSize: "0.85rem", marginBottom: "1rem" }}>
                {error}
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem", marginTop: "1.25rem" }}>
              <button type="button" className="btn btn-secondary" onClick={onClose} disabled={loading}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={loading}>
                {loading ? "Authenticating..." : "Sign In"}
              </button>
            </div>
          </form>
        ) : (
          <form onSubmit={handleSaveApiKey}>
            <div
              style={{
                padding: "0.85rem",
                borderRadius: "var(--radius-sm)",
                backgroundColor: "var(--bg-elevated)",
                border: "1px solid var(--border-subtle)",
                marginBottom: "1.25rem",
                fontSize: "0.825rem",
                color: "var(--text-secondary)",
              }}
            >
              Enter a <code className="mono">pl_test_...</code> or <code className="mono">pl_live_...</code> API key. Requests will include <code className="mono">Authorization: Bearer [key]</code>.
            </div>

            <div className="form-group">
              <label className="form-label">API KEY</label>
              <input
                type="text"
                className="form-input mono"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="pl_test_..."
                required
              />
            </div>

            {error && (
              <div style={{ color: "var(--accent-rose)", fontSize: "0.85rem", marginBottom: "1rem" }}>
                {error}
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem", marginTop: "1.25rem" }}>
              <button type="button" className="btn btn-secondary" onClick={onClose}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary">
                Save & Use API Key
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};
