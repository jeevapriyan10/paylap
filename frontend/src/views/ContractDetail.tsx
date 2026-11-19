import React, { useEffect, useState } from "react";
import { PayLapClient } from "../api/client";
import { EnvironmentBadge, StatusBadge } from "../components/Badges";
import { verifyReceiptOffline, VerificationResult } from "../utils/crypto";

export interface ContractDetailProps {
  contractId: string;
  onBack: () => void;
}

export const ContractDetail: React.FC<ContractDetailProps> = ({ contractId, onBack }) => {
  const [contract, setContract] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Submit modal state
  const [submittingMilestone, setSubmittingMilestone] = useState<number | null>(null);
  const [solutionCode, setSolutionCode] = useState<string>("");
  const [submitLoading, setSubmitLoading] = useState(false);
  const [submitOutcome, setSubmitOutcome] = useState<any>(null);

  // Receipt inspection state
  const [receiptToken, setReceiptToken] = useState<string | null>(null);
  const [receiptData, setReceiptData] = useState<any>(null);
  const [receiptLoading, setReceiptLoading] = useState(false);
  const [verificationResult, setVerificationResult] = useState<VerificationResult | null>(null);

  useEffect(() => {
    loadContract();
  }, [contractId]);

  const loadContract = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await PayLapClient.get<any>(`/v1/contracts/${contractId}`);
      setContract(data.contract || data);
    } catch (err: any) {
      setError(err?.message || "Failed to load contract details");
    } finally {
      setLoading(false);
    }
  };

  const handleOpenSubmit = (seq: number) => {
    setSubmittingMilestone(seq);
    setSolutionCode("");
    setSubmitOutcome(null);
  };

  const handleSubmitSolution = async () => {
    if (!submittingMilestone) return;
    try {
      setSubmitLoading(true);
      setSubmitOutcome(null);
      const res = await PayLapClient.post<any>(
        `/v1/contracts/${contractId}/milestones/${submittingMilestone}/submit`,
        { code: solutionCode }
      );
      setSubmitOutcome(res);
      await loadContract();
    } catch (err: any) {
      setSubmitOutcome({ passed: false, error: err?.message || "Submission failed" });
    } finally {
      setSubmitLoading(false);
    }
  };

  const handleInspectReceipt = async (token?: string) => {
    let targetToken = token || receiptToken || contract?.share_token;
    try {
      setReceiptLoading(true);
      let receipt: any = null;

      if (targetToken) {
        try {
          const data = await PayLapClient.get<any>(`/v1/receipts/${targetToken}`);
          receipt = data.receipt || data;
          setReceiptToken(targetToken);
        } catch {
          // fallback to contract receipt endpoint
        }
      }

      if (!receipt) {
        const data = await PayLapClient.get<any>(`/v1/contracts/${contractId}/receipt`);
        receipt = data.receipt || data;
      }

      setReceiptData(receipt);

      // Verify offline in browser
      const result = await verifyReceiptOffline(receipt);
      setVerificationResult(result);
    } catch (err: any) {
      alert(`Receipt is not available: ${err?.message || err}`);
    } finally {
      setReceiptLoading(false);
    }
  };

  const handleShareReceipt = async () => {
    try {
      const res = await PayLapClient.post<any>(`/v1/contracts/${contractId}/share`);
      const shareUrl = `${window.location.origin}/receipts/${res.share_token}`;
      try {
        await navigator.clipboard.writeText(shareUrl);
        alert(`Public receipt link copied to clipboard!\n${shareUrl}`);
      } catch {
        prompt("Copy this public receipt URL:", shareUrl);
      }
    } catch (err: any) {
      alert(`Failed to generate share link: ${err?.message || err}`);
    }
  };

  const handleCancelContract = async () => {
    if (!confirm("Are you sure you want to cancel this contract? Any remaining authorization hold will be voided.")) {
      return;
    }
    try {
      await PayLapClient.post(`/v1/contracts/${contractId}/cancel`);
      alert("Contract successfully cancelled and hold voided.");
      await loadContract();
    } catch (err: any) {
      alert(`Cancellation failed: ${err?.message || err}`);
    }
  };

  if (loading) {
    return (
      <div className="card" style={{ textAlign: "center", padding: "4rem" }}>
        <p style={{ color: "var(--text-secondary)" }}>Loading contract {contractId}...</p>
      </div>
    );
  }

  if (error || !contract) {
    return (
      <div>
        <button className="btn btn-secondary btn-sm" onClick={onBack} style={{ marginBottom: "1rem" }}>
          ← Back to Contracts
        </button>
        <div className="card" style={{ borderColor: "var(--accent-rose)", padding: "2rem" }}>
          <p style={{ color: "var(--accent-rose)", fontWeight: 600 }}>Error loading contract</p>
          <p style={{ color: "var(--text-secondary)", marginTop: "0.5rem" }}>{error}</p>
        </div>
      </div>
    );
  }

  const milestones: any[] = contract.milestones || [];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
        <button className="btn btn-secondary btn-sm" onClick={onBack}>
          ← Back to Contracts
        </button>
        <div style={{ display: "flex", gap: "0.75rem" }}>
          {contract.status === "FUNDED" && (
            <button className="btn btn-danger btn-sm" onClick={handleCancelContract}>
              Cancel Contract (Void Hold)
            </button>
          )}
          <button className="btn btn-secondary btn-sm" onClick={() => handleInspectReceipt()}>
            Inspect Digital Receipt
          </button>
          <button className="btn btn-primary btn-sm" onClick={handleShareReceipt}>
            Share Link
          </button>
        </div>
      </div>

      <div className="card" style={{ marginBottom: "1.5rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "1rem" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.5rem" }}>
              <h1 style={{ fontSize: "1.4rem", fontWeight: 700 }}>{contract.title}</h1>
              <EnvironmentBadge environment={contract.environment} />
              <StatusBadge status={contract.status} />
            </div>
            <div className="mono" style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
              ID: {contract.id} · Created: {new Date(contract.created_at).toLocaleString()}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "var(--accent-cyan)" }}>
              ${contract.total_usd || (contract.total_cents ? (contract.total_cents / 100).toFixed(2) : "0.00")}
            </div>
            <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>
              {contract.total_cents || 0} minor units (USD)
            </div>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1rem", marginTop: "1.5rem", borderTop: "1px solid var(--border-subtle)", paddingTop: "1.25rem" }}>
          <div>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>Worker ID</div>
            <div className="mono" style={{ fontWeight: 600, marginTop: "0.2rem" }}>{contract.worker_id}</div>
          </div>
          <div>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>Worker Recipient</div>
            <div className="mono" style={{ fontWeight: 600, marginTop: "0.2rem" }}>
              {contract.worker_email_masked || contract.worker_email || "-"}
            </div>
          </div>
          <div>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>Deadline</div>
            <div style={{ fontWeight: 600, marginTop: "0.2rem" }}>
              {contract.deadline_at ? new Date(contract.deadline_at).toLocaleDateString() : "No Expiry"}
            </div>
          </div>
          <div>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>PayPal Auth ID</div>
            <div className="mono" style={{ fontSize: "0.8rem", marginTop: "0.2rem", color: "var(--text-secondary)" }}>
              {contract.paypal_authorization_id || (contract.environment === "simulated" ? "DEMO-AUTH-SIMULATED" : "Pending")}
            </div>
          </div>
        </div>
      </div>

      <h2 style={{ fontSize: "1.15rem", fontWeight: 700, marginBottom: "0.5rem" }}>
        Milestone Execution Pipeline
      </h2>
      <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "1rem" }}>
        Deterministic sandboxed verifiers execute public and hidden test suites. Arbiter veto layer applies strictly fail-closed.
      </p>

      <div className="timeline">
        {milestones.map((m: any) => {
          const isPaid = m.status === "PAID";
          const isRejected = m.status === "REJECTED";
          return (
            <div key={m.sequence} className="timeline-item">
              <div className="timeline-marker">
                <div className={`timeline-node ${isPaid ? "passed" : isRejected ? "rejected" : ""}`}>
                  {m.sequence}
                </div>
                <div className="timeline-line"></div>
              </div>
              <div className="timeline-body">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.5rem" }}>
                  <div>
                    <span style={{ fontWeight: 600, fontSize: "0.95rem" }}>{m.title}</span>
                    <span style={{ marginLeft: "0.75rem" }}>
                      <StatusBadge status={m.status} />
                    </span>
                  </div>
                  <div style={{ fontWeight: 700, color: "var(--text-primary)" }}>
                    ${m.amount_usd || ((m.amount_cents || 0) / 100).toFixed(2)}
                  </div>
                </div>

                <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "0.75rem" }}>
                  {m.spec || "No specification provided."}
                </p>

                <div style={{ display: "flex", gap: "1.5rem", fontSize: "0.775rem", color: "var(--text-muted)", marginBottom: "0.75rem" }}>
                  <div>Verifier: <span className="mono" style={{ color: "var(--text-primary)" }}>{m.verifier_type || "python_code"}</span></div>
                  <div>Attempts: <span className="mono" style={{ color: "var(--text-primary)" }}>{m.attempts || 0} / {m.max_attempts || 2}</span></div>
                  {m.capture_id && <div>Capture ID: <span className="mono" style={{ color: "var(--accent-cyan)" }}>{m.capture_id}</span></div>}
                  {m.payout_batch_id && <div>Payout Batch: <span className="mono" style={{ color: "var(--accent-emerald)" }}>{m.payout_batch_id}</span></div>}
                </div>

                {m.public_tests && (
                  <div style={{ marginBottom: "0.75rem" }}>
                    <div style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--text-muted)", marginBottom: "0.25rem" }}>
                      PUBLIC TEST SUITE
                    </div>
                    <pre className="receipt-box" style={{ maxHeight: "120px" }}>{m.public_tests}</pre>
                  </div>
                )}

                {contract.status === "FUNDED" && m.status !== "PAID" && (
                  <div style={{ marginTop: "0.75rem" }}>
                    <button className="btn btn-primary btn-sm" onClick={() => handleOpenSubmit(m.sequence)}>
                      Submit Work Solution →
                    </button>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Submission Modal */}
      {submittingMilestone !== null && (
        <div className="modal-overlay">
          <div className="modal-content">
            <h3 style={{ fontSize: "1.2rem", fontWeight: 700, marginBottom: "0.5rem" }}>
              Submit Solution — Milestone {submittingMilestone}
            </h3>
            <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "1rem" }}>
              Code will be tested in isolated sandbox against public and hidden test commitments.
            </p>

            <div className="form-group">
              <label className="form-label">SOLUTION CODE / PAYLOAD</label>
              <textarea
                className="form-textarea"
                rows={8}
                value={solutionCode}
                onChange={(e) => setSolutionCode(e.target.value)}
                placeholder="def solution():\n    return 42"
              />
            </div>

            {submitOutcome && (
              <div
                style={{
                  padding: "0.75rem",
                  borderRadius: "var(--radius-sm)",
                  marginBottom: "1rem",
                  backgroundColor: submitOutcome.passed ? "var(--accent-emerald-bg)" : "var(--accent-rose-bg)",
                  border: `1px solid ${submitOutcome.passed ? "var(--accent-emerald)" : "var(--accent-rose)"}`,
                }}
              >
                <div style={{ fontWeight: 600, color: submitOutcome.passed ? "var(--accent-emerald)" : "var(--accent-rose)" }}>
                  {submitOutcome.passed ? "Verification Passed & Settlement Completed" : "Verification Rejected"}
                </div>
                <div style={{ fontSize: "0.8rem", color: "var(--text-primary)", marginTop: "0.25rem" }}>
                  {submitOutcome.status && <div>Status: {submitOutcome.status}</div>}
                  {submitOutcome.capture_id && <div>Capture ID: {submitOutcome.capture_id}</div>}
                  {submitOutcome.payout_batch_id && <div>Payout Batch ID: {submitOutcome.payout_batch_id}</div>}
                  {submitOutcome.error && <div>Error: {submitOutcome.error}</div>}
                </div>
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem" }}>
              <button
                className="btn btn-secondary"
                onClick={() => setSubmittingMilestone(null)}
                disabled={submitLoading}
              >
                Close
              </button>
              <button
                className="btn btn-primary"
                onClick={handleSubmitSolution}
                disabled={submitLoading || !solutionCode.trim()}
              >
                {submitLoading ? "Verifying & Settling..." : "Run Verifier & Settle"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Digital Receipt Inspector Modal */}
      {receiptData && (
        <div className="modal-overlay">
          <div className="modal-content" style={{ maxWidth: "750px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <h3 style={{ fontSize: "1.2rem", fontWeight: 700 }}>Ed25519 Cryptographic Receipt</h3>
              <button className="btn btn-secondary btn-sm" onClick={() => setReceiptData(null)}>
                Close
              </button>
            </div>

            {receiptLoading ? (
              <p style={{ color: "var(--text-secondary)" }}>Verifying cryptographic signature...</p>
            ) : (
              <div>
                {verificationResult?.valid && (
                  <div style={{ marginBottom: "1rem" }}>
                    <div className="verified-stamp">
                      <span className="badge-dot badge-dot-success" style={{ marginRight: "0.4rem" }} /> Cryptographically Verified Offline (Ed25519)
                    </div>
                    {verificationResult.publicKeyHex && (
                      <div className="mono" style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.35rem" }}>
                        Signer Key Fingerprint: {verificationResult.publicKeyHex.slice(0, 32)}...
                      </div>
                    )}
                  </div>
                )}

                <div className="form-group">
                  <label className="form-label">RECEIPT CANONICAL PAYLOAD & HASH CHAIN</label>
                  <pre className="receipt-box" style={{ maxHeight: "300px" }}>
                    {JSON.stringify(receiptData, null, 2)}
                  </pre>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "1rem" }}>
                  <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                    Zero-custody verification. Anyone can verify this receipt offline without network calls.
                  </div>
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={() => {
                      navigator.clipboard.writeText(JSON.stringify(receiptData, null, 2));
                      alert("Receipt JSON copied to clipboard!");
                    }}
                  >
                    Copy Receipt JSON
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
