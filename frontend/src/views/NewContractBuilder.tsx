import React, { useState } from "react";
import { PayLapClient } from "../api/client";
import { EnvironmentBadge } from "../components/Badges";

export interface NewContractBuilderProps {
  onContractCreated: (contractId: string) => void;
  onCancel: () => void;
}

interface MilestoneInput {
  title: string;
  amount_usd: string;
  verifier_type: "python_code" | "json_data" | "text_rules";
  spec: string;
  public_tests: string;
  hidden_tests: string;
}

export const NewContractBuilder: React.FC<NewContractBuilderProps> = ({ onContractCreated, onCancel }) => {
  const [title, setTitle] = useState("");
  const [workerId, setWorkerId] = useState("");
  const [workerEmail, setWorkerEmail] = useState("");
  const [environment, setEnvironment] = useState<"simulated" | "sandbox" | "live">("simulated");
  const [deadlineDays, setDeadlineDays] = useState(7);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [milestones, setMilestones] = useState<MilestoneInput[]>([
    {
      title: "Core Implementation",
      amount_usd: "5.00",
      verifier_type: "python_code",
      spec: "Implement calculate(a, b) returning sum",
      public_tests: "from solution import calculate\ndef test_basic(): assert calculate(2, 3) == 5",
      hidden_tests: "from solution import calculate\ndef test_edge(): assert calculate(-1, 1) == 0",
    },
  ]);

  const handleAddMilestone = () => {
    if (milestones.length >= 5) {
      alert("A contract may have a maximum of 5 milestones.");
      return;
    }
    setMilestones([
      ...milestones,
      {
        title: `Milestone ${milestones.length + 1}`,
        amount_usd: "5.00",
        verifier_type: "python_code",
        spec: "",
        public_tests: "",
        hidden_tests: "",
      },
    ]);
  };

  const handleRemoveMilestone = (index: number) => {
    if (milestones.length <= 1) return;
    setMilestones(milestones.filter((_, i) => i !== index));
  };

  const handleUpdateMilestone = (index: number, field: keyof MilestoneInput, value: string) => {
    const updated = [...milestones];
    (updated[index] as any)[field] = value;
    setMilestones(updated);
  };

  const totalCents = milestones.reduce((sum, m) => {
    const num = parseFloat(m.amount_usd || "0");
    return sum + (isNaN(num) ? 0 : Math.round(num * 100));
  }, 0);

  const totalUsd = (totalCents / 100).toFixed(2);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!title.trim() || !workerId.trim() || !workerEmail.trim()) {
      setError("Please fill in all required contract fields.");
      return;
    }

    try {
      setLoading(true);
      const deadlineDate = new Date();
      deadlineDate.setDate(deadlineDate.getDate() + deadlineDays);

      const payload = {
        title: title.trim(),
        worker_id: workerId.trim(),
        worker_email: workerEmail.trim(),
        environment,
        deadline_at: deadlineDate.toISOString(),
        milestones: milestones.map((m) => ({
          title: m.title.trim(),
          amount: m.amount_usd,
          verifier_type: m.verifier_type,
          spec: m.spec.trim(),
          public_tests: m.public_tests.trim(),
          hidden_tests: m.hidden_tests.trim(),
        })),
      };

      const idempotencyKey = `create-ctr-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
      const res = await PayLapClient.post<any>("/v1/contracts", payload, idempotencyKey);
      const newId = res.id || res.contract?.id;
      if (newId) {
        onContractCreated(newId);
      } else {
        throw new Error("Invalid response from server");
      }
    } catch (err: any) {
      setError(err?.message || "Failed to create contract.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">New Settlement Contract</h1>
          <p className="page-subtitle">Configure verified-delivery milestones, verifier test commitments, and spend policy.</p>
        </div>
        <button className="btn btn-secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>

      <form onSubmit={handleSubmit}>
        <div className="card" style={{ marginBottom: "1.5rem" }}>
          <h2 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: "1rem" }}>Contract Metadata</h2>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1rem" }}>
            <div className="form-group">
              <label className="form-label">CONTRACT TITLE *</label>
              <input
                type="text"
                className="form-input"
                placeholder="e.g. Build Data Pipeline Microservice"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">ENVIRONMENT *</label>
              <select
                className="form-select"
                value={environment}
                onChange={(e) => setEnvironment(e.target.value as any)}
              >
                <option value="simulated">Simulated (Dry Run — Instant Auto-Funding)</option>
                <option value="sandbox">Sandbox (PayPal Developer Sandbox)</option>
                <option value="live">Live (Real Funds & Production PayPal)</option>
              </select>
              <div style={{ marginTop: "0.35rem" }}>
                <EnvironmentBadge environment={environment} />
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">WORKER ID / IDENTIFIER *</label>
              <input
                type="text"
                className="form-input"
                placeholder="e.g. worker_agent_42"
                value={workerId}
                onChange={(e) => setWorkerId(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">WORKER PAYOUT EMAIL *</label>
              <input
                type="email"
                className="form-input"
                placeholder="worker@example.com"
                value={workerEmail}
                onChange={(e) => setWorkerEmail(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">DEADLINE DURATION (DAYS)</label>
              <input
                type="number"
                className="form-input"
                min={1}
                max={30}
                value={deadlineDays}
                onChange={(e) => setDeadlineDays(parseInt(e.target.value) || 7)}
              />
            </div>
          </div>
        </div>

        <div className="card" style={{ marginBottom: "1.5rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <div>
              <h2 style={{ fontSize: "1.1rem", fontWeight: 700 }}>Milestones & Deterministic Verifiers</h2>
              <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)" }}>
                Up to 5 sequential milestones. Hidden test commitments are hashed (SHA-256) and never returned to workers.
              </p>
            </div>
            {milestones.length < 5 && (
              <button type="button" className="btn btn-secondary btn-sm" onClick={handleAddMilestone}>
                + Add Milestone
              </button>
            )}
          </div>

          {milestones.map((m, idx) => (
            <div
              key={idx}
              style={{
                backgroundColor: "var(--bg-elevated)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-md)",
                padding: "1.25rem",
                marginBottom: "1rem",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
                <span style={{ fontWeight: 700, fontSize: "0.95rem" }}>Milestone {idx + 1}</span>
                {milestones.length > 1 && (
                  <button
                    type="button"
                    className="btn btn-danger btn-sm"
                    onClick={() => handleRemoveMilestone(idx)}
                  >
                    Remove
                  </button>
                )}
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: "1rem", marginBottom: "0.75rem" }}>
                <div className="form-group">
                  <label className="form-label">MILESTONE TITLE</label>
                  <input
                    type="text"
                    className="form-input"
                    value={m.title}
                    onChange={(e) => handleUpdateMilestone(idx, "title", e.target.value)}
                    required
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">AMOUNT (USD)</label>
                  <input
                    type="text"
                    className="form-input"
                    value={m.amount_usd}
                    onChange={(e) => handleUpdateMilestone(idx, "amount_usd", e.target.value)}
                    required
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">VERIFIER TYPE</label>
                  <select
                    className="form-select"
                    value={m.verifier_type}
                    onChange={(e) => handleUpdateMilestone(idx, "verifier_type", e.target.value as any)}
                  >
                    <option value="python_code">Python Sandbox</option>
                    <option value="json_data">JSON Schema</option>
                    <option value="text_rules">Deterministic Text Rules</option>
                  </select>
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">SPECIFICATION / REQUIREMENTS</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="Task instructions given to worker..."
                  value={m.spec}
                  onChange={(e) => handleUpdateMilestone(idx, "spec", e.target.value)}
                />
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                <div className="form-group">
                  <label className="form-label">PUBLIC TESTS (VISIBLE TO WORKER)</label>
                  <textarea
                    className="form-textarea"
                    rows={4}
                    placeholder="def test_example(): assert True"
                    value={m.public_tests}
                    onChange={(e) => handleUpdateMilestone(idx, "public_tests", e.target.value)}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">HIDDEN TESTS (CONFIDENTIAL COMMITMENT)</label>
                  <textarea
                    className="form-textarea"
                    rows={4}
                    placeholder="def test_hidden(): assert edge_case == expected"
                    value={m.hidden_tests}
                    onChange={(e) => handleUpdateMilestone(idx, "hidden_tests", e.target.value)}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Policy & Total Summary */}
        <div className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
          <div>
            <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>TOTAL HOLD AMOUNT</div>
            <div style={{ fontSize: "1.6rem", fontWeight: 700, color: "var(--accent-cyan)" }}>
              ${totalUsd} <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>({totalCents} minor units)</span>
            </div>
          </div>

          <div style={{ display: "flex", gap: "0.75rem" }}>
            <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={loading}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? "Creating & Initializing Hold..." : "Create Settlement Contract"}
            </button>
          </div>
        </div>

        {error && (
          <div className="card" style={{ borderColor: "var(--accent-rose)", padding: "1.25rem", marginBottom: "1.5rem" }}>
            <p style={{ color: "var(--accent-rose)", fontWeight: 600 }}>Error creating contract</p>
            <p style={{ color: "var(--text-secondary)", marginTop: "0.25rem" }}>{error}</p>
          </div>
        )}
      </form>
    </div>
  );
};
