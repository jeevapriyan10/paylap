import React, { useEffect, useState } from "react";
import { PayLapClient } from "../api/client";

export const Settings: React.FC = () => {
  const [activeTab, setActiveTab] = useState<"paypal" | "policy" | "webhooks" | "apikeys">("paypal");

  // PayPal credentials state
  const [ppEnv, setPpEnv] = useState<"sandbox" | "live">("sandbox");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [ppLoading, setPpLoading] = useState(false);
  const [ppStatus, setPpStatus] = useState<string | null>(null);

  // Spend Policy state
  const [maxTaskUsd, setMaxTaskUsd] = useState("50.00");
  const [dailyCapUsd, setDailyCapUsd] = useState("500.00");
  const [maxMilestones, setMaxMilestones] = useState(5);
  const [requireHidden, setRequireHidden] = useState(true);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [policyMsg, setPolicyMsg] = useState<string | null>(null);

  // Webhooks state
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhooksList, setWebhooksList] = useState<any[]>([]);

  // API Keys state
  const [apiKeys, setApiKeys] = useState<any[]>([]);
  const [showKeyModal, setShowKeyModal] = useState(false);
  const [newKeyEnv, setNewKeyEnv] = useState<"test" | "live">("test");
  const [generatedKey, setGeneratedKey] = useState<string | null>(null);

  useEffect(() => {
    loadSettings();
  }, [activeTab]);

  const loadSettings = async () => {
    try {
      if (activeTab === "policy") {
        const policy = await PayLapClient.get<any>("/v1/org/policy/simulated");
        if (policy) {
          setMaxTaskUsd(((policy.max_task_cents || 5000) / 100).toFixed(2));
          setDailyCapUsd(((policy.daily_cap_cents || 50000) / 100).toFixed(2));
          setMaxMilestones(policy.max_milestones || 5);
          setRequireHidden(policy.require_hidden_tests ?? true);
        }
      } else if (activeTab === "webhooks") {
        const endpoints = await PayLapClient.get<any>("/v1/org/webhooks");
        setWebhooksList(Array.isArray(endpoints) ? endpoints : endpoints.items || []);
      } else if (activeTab === "apikeys") {
        const keys = await PayLapClient.get<any>("/v1/org/api-keys");
        setApiKeys(Array.isArray(keys) ? keys : keys.items || []);
      }
    } catch {
      // Fallback gracefully for initial state
    }
  };

  const handleSavePayPal = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setPpLoading(true);
      setPpStatus(null);
      await PayLapClient.put(`/v1/org/paypal/${ppEnv}`, {
        client_id: clientId.trim(),
        client_secret: clientSecret.trim(),
      });
      setPpStatus("Credentials saved and encrypted with AES-256-GCM.");
      setClientSecret("");
    } catch (err: any) {
      setPpStatus(`Failed to save: ${err?.message || err}`);
    } finally {
      setPpLoading(false);
    }
  };

  const handleVerifyPayPal = async () => {
    try {
      setPpLoading(true);
      setPpStatus("Testing OAuth token handshake with PayPal...");
      const res = await PayLapClient.post<any>(`/v1/org/paypal/${ppEnv}/verify`);
      if (res.verified) {
        setPpStatus(`Successfully verified OAuth with PayPal ${ppEnv} at ${res.verified_at}`);
      } else {
        setPpStatus(`Verification failed: ${res.error || "Invalid response"}`);
      }
    } catch (err: any) {
      setPpStatus(`Verification error: ${err?.message || err}`);
    } finally {
      setPpLoading(false);
    }
  };

  const handleSavePolicy = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setPolicyLoading(true);
      setPolicyMsg(null);
      const taskCents = Math.round(parseFloat(maxTaskUsd) * 100);
      const capCents = Math.round(parseFloat(dailyCapUsd) * 100);

      await PayLapClient.put("/v1/org/policy/simulated", {
        max_task_cents: taskCents,
        daily_cap_cents: capCents,
        max_milestones: maxMilestones,
        require_hidden_tests: requireHidden,
        max_contract_days: 28,
      });
      setPolicyMsg("Policy configuration updated successfully.");
    } catch (err: any) {
      setPolicyMsg(`Error updating policy: ${err?.message || err}`);
    } finally {
      setPolicyLoading(false);
    }
  };

  const handleCreateWebhook = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!webhookUrl.trim()) return;
    try {
      await PayLapClient.post("/v1/org/webhooks", {
        url: webhookUrl.trim(),
        event_types: ["MILESTONE_PAID", "CONTRACT_COMPLETED", "AUTHORIZATION_VOIDED"],
      });
      setWebhookUrl("");
      await loadSettings();
    } catch (err: any) {
      alert(`Failed to add webhook: ${err?.message || err}`);
    }
  };

  const handlePingWebhook = async (endpointId: string) => {
    try {
      const res = await PayLapClient.post<any>(`/v1/org/webhooks/${endpointId}/ping`);
      alert(`Ping sent! Delivery ID: ${res.delivery_id || res.id}, Status: ${res.status_code || "dispatched"}`);
    } catch (err: any) {
      alert(`Ping failed: ${err?.message || err}`);
    }
  };

  const handleGenerateKey = async () => {
    try {
      const res = await PayLapClient.post<any>("/v1/org/api-keys", {
        environment_class: newKeyEnv,
        scopes: ["contracts:read", "contracts:write", "workers:read", "receipts:read", "playground:run"],
      });
      setGeneratedKey(res.api_key || res.key);
      await loadSettings();
    } catch (err: any) {
      alert(`Failed to generate API key: ${err?.message || err}`);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Organization Settings</h1>
          <p className="page-subtitle">Configure PayPal BYO credentials, spend policy, webhooks, and API keys.</p>
        </div>
      </div>

      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1.5rem", borderBottom: "1px solid var(--border-subtle)", paddingBottom: "0.5rem" }}>
        <button
          className={`nav-link ${activeTab === "paypal" ? "active" : ""}`}
          onClick={() => setActiveTab("paypal")}
        >
          PayPal Credentials
        </button>
        <button
          className={`nav-link ${activeTab === "policy" ? "active" : ""}`}
          onClick={() => setActiveTab("policy")}
        >
          Spend Policy
        </button>
        <button
          className={`nav-link ${activeTab === "webhooks" ? "active" : ""}`}
          onClick={() => setActiveTab("webhooks")}
        >
          Webhooks
        </button>
        <button
          className={`nav-link ${activeTab === "apikeys" ? "active" : ""}`}
          onClick={() => setActiveTab("apikeys")}
        >
          API Keys
        </button>
      </div>

      {activeTab === "paypal" && (
        <div className="card" style={{ maxWidth: "600px" }}>
          <h2 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: "0.5rem" }}>
            Bring-Your-Own (BYO) PayPal Credentials
          </h2>
          <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "1.25rem" }}>
            Stored encrypted with AES-256-GCM using authenticated additional data (AAD). PayLap never custodies funds.
          </p>

          <form onSubmit={handleSavePayPal}>
            <div className="form-group">
              <label className="form-label">ENVIRONMENT</label>
              <select
                className="form-select"
                value={ppEnv}
                onChange={(e) => setPpEnv(e.target.value as any)}
              >
                <option value="sandbox">Sandbox (api-m.sandbox.paypal.com)</option>
                <option value="live">Live (api-m.paypal.com)</option>
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">PAYPAL CLIENT ID *</label>
              <input
                type="text"
                className="form-input"
                placeholder="A21AA..."
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">PAYPAL CLIENT SECRET *</label>
              <input
                type="password"
                className="form-input"
                placeholder="••••••••••••••••••••••••"
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
                required
              />
            </div>

            <div style={{ display: "flex", gap: "0.75rem", marginTop: "1rem" }}>
              <button type="submit" className="btn btn-primary" disabled={ppLoading}>
                {ppLoading ? "Saving..." : "Save Credentials"}
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleVerifyPayPal}
                disabled={ppLoading}
              >
                Verify OAuth Handshake
              </button>
            </div>

            {ppStatus && (
              <div style={{ marginTop: "1rem", fontSize: "0.85rem", color: "var(--accent-cyan)" }}>
                {ppStatus}
              </div>
            )}
          </form>
        </div>
      )}

      {activeTab === "policy" && (
        <div className="card" style={{ maxWidth: "600px" }}>
          <h2 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: "0.5rem" }}>
            Organization Spend & Risk Policy
          </h2>
          <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "1.25rem" }}>
            Contracts violating these limits are rejected deterministically before any PayPal authorization hold.
          </p>

          <form onSubmit={handleSavePolicy}>
            <div className="form-group">
              <label className="form-label">MAX SINGLE TASK AMOUNT (USD)</label>
              <input
                type="text"
                className="form-input"
                value={maxTaskUsd}
                onChange={(e) => setMaxTaskUsd(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">DAILY ORG SPEND CAP (USD)</label>
              <input
                type="text"
                className="form-input"
                value={dailyCapUsd}
                onChange={(e) => setDailyCapUsd(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">MAX MILESTONES PER CONTRACT</label>
              <input
                type="number"
                className="form-input"
                min={1}
                max={5}
                value={maxMilestones}
                onChange={(e) => setMaxMilestones(parseInt(e.target.value) || 5)}
                required
              />
            </div>

            <div className="form-group" style={{ flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
              <input
                type="checkbox"
                id="req-hidden"
                checked={requireHidden}
                onChange={(e) => setRequireHidden(e.target.checked)}
              />
              <label htmlFor="req-hidden" className="form-label" style={{ marginBottom: 0 }}>
                Require hidden test commitments on every milestone
              </label>
            </div>

            <button type="submit" className="btn btn-primary" style={{ marginTop: "1rem" }} disabled={policyLoading}>
              {policyLoading ? "Saving Policy..." : "Update Policy Rules"}
            </button>

            {policyMsg && (
              <div style={{ marginTop: "1rem", fontSize: "0.85rem", color: "var(--accent-emerald)" }}>
                {policyMsg}
              </div>
            )}
          </form>
        </div>
      )}

      {activeTab === "webhooks" && (
        <div>
          <div className="card" style={{ maxWidth: "600px", marginBottom: "1.5rem" }}>
            <h2 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: "0.5rem" }}>
              Register Outbound Webhook
            </h2>
            <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "1rem" }}>
              PayLap sends HMAC-SHA256 signed event payloads with automatic exponential backoff retry.
            </p>

            <form onSubmit={handleCreateWebhook}>
              <div className="form-group">
                <label className="form-label">ENDPOINT HTTPS URL *</label>
                <input
                  type="url"
                  className="form-input"
                  placeholder="https://api.yourdomain.com/webhooks/paylap"
                  value={webhookUrl}
                  onChange={(e) => setWebhookUrl(e.target.value)}
                  required
                />
              </div>

              <button type="submit" className="btn btn-primary">
                Add Endpoint
              </button>
            </form>
          </div>

          <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: "0.75rem" }}>
            Configured Endpoints
          </h3>
          {webhooksList.length === 0 ? (
            <div className="card" style={{ color: "var(--text-muted)" }}>
              No webhook endpoints configured yet.
            </div>
          ) : (
            <div className="table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>URL</th>
                    <th>Events</th>
                    <th>Status</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {webhooksList.map((wh) => (
                    <tr key={wh.id}>
                      <td className="mono" style={{ color: "var(--accent-cyan)" }}>{wh.url}</td>
                      <td>{Array.isArray(wh.event_types) ? wh.event_types.join(", ") : "All"}</td>
                      <td>{wh.disabled_at ? "Disabled" : "Active"}</td>
                      <td>
                        <button className="btn btn-secondary btn-sm" onClick={() => handlePingWebhook(wh.id)}>
                          Ping
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeTab === "apikeys" && (
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <div>
              <h2 style={{ fontSize: "1.1rem", fontWeight: 700 }}>Programmatic API Keys</h2>
              <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)" }}>
                Authenticate requests via <code className="mono">Authorization: Bearer pl_...</code> header.
              </p>
            </div>
            <button className="btn btn-primary btn-sm" onClick={() => setShowKeyModal(true)}>
              + Generate API Key
            </button>
          </div>

          {apiKeys.length === 0 ? (
            <div className="card" style={{ color: "var(--text-muted)" }}>
              No API keys generated yet.
            </div>
          ) : (
            <div className="table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Lookup ID / Prefix</th>
                    <th>Environment</th>
                    <th>Last 4</th>
                    <th>Scopes</th>
                    <th>Created At</th>
                  </tr>
                </thead>
                <tbody>
                  {apiKeys.map((k) => (
                    <tr key={k.id}>
                      <td className="mono">{k.lookup_id || k.id}</td>
                      <td>
                        <span className="badge badge-sandbox">{k.environment_class || "test"}</span>
                      </td>
                      <td className="mono">•••• {k.last4}</td>
                      <td style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>
                        {Array.isArray(k.scopes) ? k.scopes.join(", ") : "-"}
                      </td>
                      <td style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                        {k.created_at ? new Date(k.created_at).toLocaleDateString() : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* New Key Drawer / Modal */}
          {showKeyModal && (
            <div className="modal-overlay">
              <div className="modal-content" style={{ maxWidth: "550px" }}>
                <h3 style={{ fontSize: "1.2rem", fontWeight: 700, marginBottom: "0.5rem" }}>
                  Generate New API Key
                </h3>

                {!generatedKey ? (
                  <div>
                    <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "1rem" }}>
                      Choose environment class. Test keys cannot settle live transactions.
                    </p>

                    <div className="form-group">
                      <label className="form-label">ENVIRONMENT CLASS</label>
                      <select
                        className="form-select"
                        value={newKeyEnv}
                        onChange={(e) => setNewKeyEnv(e.target.value as any)}
                      >
                        <option value="test">Test (pl_test_...)</option>
                        <option value="live">Live (pl_live_...)</option>
                      </select>
                    </div>

                    <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem", marginTop: "1.5rem" }}>
                      <button className="btn btn-secondary" onClick={() => setShowKeyModal(false)}>
                        Cancel
                      </button>
                      <button className="btn btn-primary" onClick={handleGenerateKey}>
                        Create Secret Key
                      </button>
                    </div>
                  </div>
                ) : (
                  <div>
                    <div
                      style={{
                        padding: "1rem",
                        backgroundColor: "var(--accent-amber-bg)",
                        border: "1px solid var(--accent-amber)",
                        borderRadius: "var(--radius-sm)",
                        marginBottom: "1rem",
                      }}
                    >
                      <div style={{ fontWeight: 700, color: "var(--accent-amber)", marginBottom: "0.25rem" }}>
                        IMPORTANT: COPY YOUR KEY NOW
                      </div>
                      <div style={{ fontSize: "0.85rem", color: "var(--text-primary)" }}>
                        This is the only time the full secret key is displayed. PayLap only stores a SHA-256 hash.
                      </div>
                    </div>

                    <div className="form-group">
                      <label className="form-label">FULL API KEY</label>
                      <div style={{ display: "flex", gap: "0.5rem" }}>
                        <input
                          type="text"
                          readOnly
                          className="form-input mono"
                          style={{ flex: 1, backgroundColor: "#080a0e" }}
                          value={generatedKey}
                        />
                        <button
                          className="btn btn-secondary"
                          onClick={() => {
                            navigator.clipboard.writeText(generatedKey);
                            alert("API Key copied to clipboard!");
                          }}
                        >
                          Copy
                        </button>
                      </div>
                    </div>

                    <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "1.5rem" }}>
                      <button
                        className="btn btn-primary"
                        onClick={() => {
                          setGeneratedKey(null);
                          setShowKeyModal(false);
                        }}
                      >
                        I Have Copied My Key
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
