import React, { useEffect, useState } from "react";
import { PayLapClient } from "../api/client";
import { EnvironmentBadge, StatusBadge } from "../components/Badges";

export interface MilestoneSummary {
  sequence: number;
  title: string;
  amount_cents: number;
  amount_usd: string;
  status: string;
}

export interface ContractItem {
  id: string;
  title: string;
  worker_id: string;
  worker_email?: string;
  environment: string;
  status: string;
  total_cents: number;
  total_usd: string;
  created_at: string;
  deadline_at?: string;
  milestones: MilestoneSummary[];
}

export interface ContractsListProps {
  onSelectContract: (id: string) => void;
  onNavigateNew: () => void;
  onOpenAuth?: () => void;
}

export const ContractsList: React.FC<ContractsListProps> = ({ onSelectContract, onNavigateNew, onOpenAuth }) => {
  const [contracts, setContracts] = useState<ContractItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [statusFilter, setStatusFilter] = useState<string>("");
  const [envFilter, setEnvFilter] = useState<string>("");
  const [searchTerm, setSearchTerm] = useState<string>("");

  useEffect(() => {
    loadContracts();
    const handleAuthChange = () => loadContracts();
    window.addEventListener("paylap_auth_change", handleAuthChange);
    return () => window.removeEventListener("paylap_auth_change", handleAuthChange);
  }, [statusFilter, envFilter]);

  const loadContracts = async () => {
    try {
      setLoading(true);
      setError(null);
      let query = "/v1/contracts?limit=50";
      if (statusFilter) query += `&status=${encodeURIComponent(statusFilter)}`;
      if (envFilter) query += `&environment=${encodeURIComponent(envFilter)}`;

      const data = await PayLapClient.get<any>(query);
      const items = data.items || data.contracts || (Array.isArray(data) ? data : []);
      setContracts(items);
    } catch (err: any) {
      setError(err?.message || "Failed to load contracts");
    } finally {
      setLoading(false);
    }
  };

  const filteredContracts = contracts.filter((c) => {
    if (!searchTerm) return true;
    const term = searchTerm.toLowerCase();
    return (
      c.title.toLowerCase().includes(term) ||
      c.id.toLowerCase().includes(term) ||
      (c.worker_id && c.worker_id.toLowerCase().includes(term))
    );
  });

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Contracts</h1>
          <p className="page-subtitle">Multi-tenant verified-delivery payment holds and milestone settlements.</p>
        </div>
        <button className="btn btn-primary" onClick={onNavigateNew}>
          + New Contract
        </button>
      </div>

      <div className="card" style={{ marginBottom: "1.5rem" }}>
        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
          <div style={{ flex: 1, minWidth: "240px" }}>
            <input
              type="text"
              className="form-input"
              style={{ width: "100%" }}
              placeholder="Search contracts by title, ID, or worker..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
          <div style={{ width: "160px" }}>
            <select
              className="form-select"
              style={{ width: "100%" }}
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="">All Statuses</option>
              <option value="AWAITING_FUNDING">Awaiting Funding</option>
              <option value="FUNDED">Funded</option>
              <option value="COMPLETED">Completed</option>
              <option value="VOIDED">Voided</option>
              <option value="BLOCKED">Blocked</option>
            </select>
          </div>
          <div style={{ width: "160px" }}>
            <select
              className="form-select"
              style={{ width: "100%" }}
              value={envFilter}
              onChange={(e) => setEnvFilter(e.target.value)}
            >
              <option value="">All Environments</option>
              <option value="simulated">Simulated (Dry Run)</option>
              <option value="sandbox">Sandbox</option>
              <option value="live">Live</option>
            </select>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="card" style={{ textAlign: "center", padding: "3rem" }}>
          <p style={{ color: "var(--text-secondary)" }}>Loading settlement contracts...</p>
        </div>
      ) : error ? (
        <div
          className="card"
          style={{
            borderColor: error.includes("Authentication") ? "var(--accent-amber)" : "var(--accent-rose)",
            padding: "2.5rem",
            textAlign: "center",
          }}
        >
          <p
            style={{
              color: error.includes("Authentication") ? "var(--accent-amber)" : "var(--accent-rose)",
              fontWeight: 700,
              fontSize: "1.1rem",
            }}
          >
            {error.includes("Authentication") ? "Authentication Required" : "Error Loading Contracts"}
          </p>
          <p
            style={{
              color: "var(--text-secondary)",
              maxWidth: "480px",
              margin: "0.5rem auto 1.5rem auto",
            }}
          >
            {error.includes("Authentication")
              ? "Sign in to your organization or provide a developer API key to view and manage settlement contracts."
              : error}
          </p>
          {error.includes("Authentication") && (
            <div style={{ display: "flex", gap: "0.75rem", justifyContent: "center", flexWrap: "wrap" }}>
              <button
                className="btn btn-primary"
                onClick={async () => {
                  try {
                    const res = await PayLapClient.post<any>("/v1/auth/login", {
                      email: "dev@paylap.local",
                      password: "Development1234!",
                    });
                    if (res?.csrf_token) localStorage.setItem("paylap_csrf_token", res.csrf_token);
                    if (res?.user) localStorage.setItem("paylap_user", JSON.stringify(res.user));
                    window.dispatchEvent(new Event("paylap_auth_change"));
                    loadContracts();
                  } catch {
                    localStorage.setItem("paylap_api_key", "pl_test_devkey00000000_1234567890abcdef1234567890abcdef");
                    window.dispatchEvent(new Event("paylap_auth_change"));
                    loadContracts();
                  }
                }}
              >
                1-Click Sign In as Dev
              </button>
              {onOpenAuth && (
                <button className="btn btn-secondary" onClick={onOpenAuth}>
                  Custom Sign In
                </button>
              )}
            </div>
          )}
        </div>
      ) : filteredContracts.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: "4rem 2rem" }}>
          <p style={{ color: "var(--text-secondary)", fontSize: "1.1rem" }}>No contracts match your criteria.</p>
          <button className="btn btn-secondary btn-sm" style={{ marginTop: "1rem" }} onClick={onNavigateNew}>
            Create First Contract
          </button>
        </div>
      ) : (
        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Contract ID / Title</th>
                <th>Environment</th>
                <th>Status</th>
                <th>Milestones</th>
                <th>Total (USD)</th>
                <th>Worker</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {filteredContracts.map((ctr) => (
                <tr key={ctr.id} onClick={() => onSelectContract(ctr.id)} style={{ cursor: "pointer" }}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{ctr.title}</div>
                    <div className="mono" style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                      {ctr.id}
                    </div>
                  </td>
                  <td>
                    <EnvironmentBadge environment={ctr.environment} />
                  </td>
                  <td>
                    <StatusBadge status={ctr.status} />
                  </td>
                  <td>
                    {ctr.milestones ? (
                      <span style={{ color: "var(--text-secondary)" }}>
                        {ctr.milestones.filter((m) => m.status === "PAID").length} / {ctr.milestones.length} paid
                      </span>
                    ) : (
                      "-"
                    )}
                  </td>
                  <td style={{ fontWeight: 600 }}>
                    ${ctr.total_usd || (ctr.total_cents ? (ctr.total_cents / 100).toFixed(2) : "0.00")}
                  </td>
                  <td className="mono" style={{ color: "var(--text-secondary)" }}>
                    {ctr.worker_id}
                  </td>
                  <td>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectContract(ctr.id);
                      }}
                    >
                      View →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
