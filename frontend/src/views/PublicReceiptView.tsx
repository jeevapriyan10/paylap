import React, { useEffect, useState } from "react";
import { PayLapClient } from "../api/client";
import { verifyReceiptOffline, VerificationResult } from "../utils/crypto";

export interface PublicReceiptViewProps {
  shareToken: string;
}

export const PublicReceiptView: React.FC<PublicReceiptViewProps> = ({ shareToken }) => {
  const [receipt, setReceipt] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [verification, setVerification] = useState<VerificationResult | null>(null);

  useEffect(() => {
    loadAndVerify();
  }, [shareToken]);

  const loadAndVerify = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await PayLapClient.get<any>(`/v1/receipts/${shareToken}`);
      const r = data.receipt || data;
      setReceipt(r);

      // Verify Ed25519 signature offline using browser WebCrypto
      const result = await verifyReceiptOffline(r);
      setVerification(result);
    } catch (err: any) {
      setError(err?.message || "Failed to load public receipt");
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="card" style={{ maxWidth: "680px", margin: "3rem auto", textAlign: "center", padding: "4rem 2rem" }}>
        <p style={{ color: "var(--text-secondary)" }}>Fetching verifiable settlement receipt...</p>
      </div>
    );
  }

  if (error || !receipt) {
    return (
      <div className="card" style={{ maxWidth: "680px", margin: "3rem auto", borderColor: "var(--accent-rose)", padding: "2.5rem" }}>
        <h2 style={{ color: "var(--accent-rose)", fontSize: "1.2rem", fontWeight: 700, marginBottom: "0.5rem" }}>
          Invalid or Expired Receipt Token
        </h2>
        <p style={{ color: "var(--text-secondary)" }}>{error || "Receipt not found."}</p>
      </div>
    );
  }

  const isSimulated = receipt.simulated ?? true;

  return (
    <div style={{ maxWidth: "720px", margin: "2rem auto" }}>
      <div className="card" style={{ padding: "2rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.5rem" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "0.4rem" }}>
              <h1 style={{ fontSize: "1.5rem", fontWeight: 700 }}>Settlement Receipt</h1>
              <span className="badge" style={{ backgroundColor: "var(--bg-elevated)", color: "var(--text-secondary)" }}>
                v{receipt.receipt_version || 2}
              </span>
            </div>
            <div className="mono" style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
              Share Token: {shareToken}
            </div>
          </div>

          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "var(--accent-emerald)" }}>
              ${receipt.amount_usd || ((receipt.amount_cents || 0) / 100).toFixed(2)}
            </div>
            <div className="mono" style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              {receipt.amount_cents} cents · {receipt.currency || "USD"}
            </div>
          </div>
        </div>

        {/* Cryptographic Verification Badge */}
        <div
          style={{
            padding: "1rem",
            borderRadius: "var(--radius-sm)",
            backgroundColor: verification?.valid ? "var(--accent-emerald-bg)" : "var(--accent-rose-bg)",
            border: `1px solid ${verification?.valid ? "var(--accent-emerald)" : "var(--accent-rose)"}`,
            marginBottom: "1.5rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span style={{ fontSize: "1.2rem", color: verification?.valid ? "var(--accent-emerald)" : "var(--accent-rose)" }}>
              {verification?.valid ? "✓" : "✗"}
            </span>
            <span style={{ fontWeight: 700, color: verification?.valid ? "var(--accent-emerald)" : "var(--accent-rose)" }}>
              {verification?.valid
                ? "Cryptographically Verified Offline via Ed25519"
                : "Cryptographic Verification Failed"}
            </span>
          </div>

          <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)", marginTop: "0.4rem" }}>
            {verification?.valid
              ? "The digital signature and event hash chain have been independently validated in your browser. PayLap never custodies funds."
              : verification?.error || "Signature does not match payload."}
          </div>

          {verification?.publicKeyHex && (
            <div className="mono" style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.35rem" }}>
              Signer Public Key: {verification.publicKeyHex}
            </div>
          )}
        </div>

        {/* Settlement Details */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
            gap: "1.25rem",
            borderTop: "1px solid var(--border-subtle)",
            borderBottom: "1px solid var(--border-subtle)",
            padding: "1.25rem 0",
            marginBottom: "1.5rem",
          }}
        >
          <div>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>Contract ID</div>
            <div className="mono" style={{ fontWeight: 600, marginTop: "0.2rem" }}>{receipt.contract_id}</div>
          </div>

          <div>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>Milestone Index</div>
            <div style={{ fontWeight: 600, marginTop: "0.2rem" }}>Milestone #{receipt.milestone_idx}</div>
          </div>

          <div>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>Worker Recipient</div>
            <div className="mono" style={{ fontWeight: 600, marginTop: "0.2rem" }}>
              {receipt.worker_email_masked || "Masked Recipient"}
            </div>
          </div>

          <div>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>PayPal Capture ID</div>
            <div className="mono" style={{ color: "var(--accent-cyan)", marginTop: "0.2rem" }}>
              {receipt.capture_id || "-"}
            </div>
          </div>

          <div>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>PayPal Payout Batch</div>
            <div className="mono" style={{ color: "var(--accent-emerald)", marginTop: "0.2rem" }}>
              {receipt.payout_batch_id || "-"}
            </div>
          </div>

          <div>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>Settlement Mode</div>
            <div style={{ marginTop: "0.2rem" }}>
              {isSimulated ? (
                <span className="badge badge-simulated">Simulated (Dry Run)</span>
              ) : (
                <span className="badge badge-live">Verified Settlement</span>
              )}
            </div>
          </div>
        </div>

        {/* Raw Canonical Payload */}
        <div className="form-group">
          <label className="form-label">CANONICAL RECEIPT JSON (RFC 8785)</label>
          <pre className="receipt-box" style={{ maxHeight: "240px" }}>
            {JSON.stringify(receipt, null, 2)}
          </pre>
        </div>

        <div style={{ textAlign: "center", marginTop: "1rem" }}>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => {
              navigator.clipboard.writeText(JSON.stringify(receipt, null, 2));
              alert("Receipt JSON copied to clipboard!");
            }}
          >
            Copy Raw Receipt for Offline CLI Verification
          </button>
        </div>
      </div>
    </div>
  );
};
