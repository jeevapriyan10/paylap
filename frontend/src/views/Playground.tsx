import React, { useState } from "react";
import { PayLapClient } from "../api/client";

interface ScenarioDef {
  key: string;
  title: string;
  description: string;
  budget_usd: string;
  expected_outcome: string;
  expected_layer: string;
}

const SCENARIOS: ScenarioDef[] = [
  {
    key: "honest",
    title: "Honest Worker",
    description: "Worker submits clean solution passing both public and hidden tests.",
    budget_usd: "5.00",
    expected_outcome: "PAID / COMPLETED",
    expected_layer: "Settlement & Capture",
  },
  {
    key: "buggy",
    title: "Buggy Implementation",
    description: "Worker submits flawed code failing assertion checks in sandbox.",
    budget_usd: "5.00",
    expected_outcome: "REJECTED / VOIDED",
    expected_layer: "Deterministic Verifier",
  },
  {
    key: "cheater",
    title: "Hardcoded Cheater",
    description: "Worker hardcodes answers for public tests but fails hidden commitments.",
    budget_usd: "5.00",
    expected_outcome: "REJECTED / VOIDED",
    expected_layer: "Hidden Test Commitment",
  },
  {
    key: "malicious",
    title: "Sandbox Breakout Attempt",
    description: "Worker attempts forbidden OS system calls and unwhitelisted modules.",
    budget_usd: "5.00",
    expected_outcome: "BLOCKED",
    expected_layer: "Process AST Sandbox",
  },
  {
    key: "injector",
    title: "Prompt Injection Attack",
    description: "Worker embeds adversarial prompt injection trying to force approval.",
    budget_usd: "5.00",
    expected_outcome: "BLOCKED / VETOED",
    expected_layer: "Fail-Closed Arbiter Veto",
  },
  {
    key: "overspender",
    title: "Spend Policy Bypass",
    description: "Contract attempts to exceed configured org budget limit ($500.00).",
    budget_usd: "600.00",
    expected_outcome: "BLOCKED (422)",
    expected_layer: "Org Spend Policy Engine",
  },
];

export const Playground: React.FC = () => {
  const [running, setRunning] = useState(false);
  const [activeScenario, setActiveScenario] = useState<string | null>(null);
  const [results, setResults] = useState<any[]>([]);
  const [ledgerValid, setLedgerValid] = useState<boolean | null>(null);
  const [logs, setLogs] = useState<string[]>([]);

  const addLog = (msg: string) => {
    setLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);
  };

  const runAllScenarios = async () => {
    try {
      setRunning(true);
      setActiveScenario("all");
      setLogs([]);
      setResults([]);
      setLedgerValid(null);

      addLog("Starting Red Team Arena execution: 6 adversarial scenarios...");
      const res = await PayLapClient.post<any>("/v1/arena/run", { scenario: "all", sync: true });

      const scenarioResults = res.scenarios || [];
      setResults(scenarioResults);
      setLedgerValid(res.ledger_chain_valid);

      scenarioResults.forEach((r: any) => {
        addLog(
          `Scenario [${r.scenario}]: ${r.passed ? "PASSED (Defense Held)" : "FAILED"} — Status: ${r.status || r.actual_outcome} (${r.elapsed_ms}ms)`
        );
      });

      if (res.ledger_chain_valid) {
        addLog("Cryptographic Ledger Integrity: 100% verified from genesis to head.");
      }
    } catch (err: any) {
      addLog(`Execution error: ${err?.message || err}`);
    } finally {
      setRunning(false);
      setActiveScenario(null);
    }
  };

  const runSingleScenario = async (key: string) => {
    try {
      setRunning(true);
      setActiveScenario(key);
      addLog(`Executing scenario: ${key}...`);

      const res = await PayLapClient.post<any>("/v1/arena/run", { scenario: key, sync: true });
      const scenarioResults = res.scenarios || [];
      setResults(scenarioResults);
      setLedgerValid(res.ledger_chain_valid);

      scenarioResults.forEach((r: any) => {
        addLog(
          `Scenario [${r.scenario}]: ${r.passed ? "PASSED (Defense Held)" : "FAILED"} — Status: ${r.status || r.actual_outcome} (${r.elapsed_ms}ms)`
        );
      });
    } catch (err: any) {
      addLog(`Scenario ${key} failed: ${err?.message || err}`);
    } finally {
      setRunning(false);
      setActiveScenario(null);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Red Team Arena & Playground</h1>
          <p className="page-subtitle">
            Autonomous multi-agent adversarial simulation proving deterministic gates, AST isolation, and fail-closed arbiter defense.
          </p>
        </div>
        <button
          className="btn btn-primary"
          onClick={runAllScenarios}
          disabled={running}
        >
          {running && activeScenario === "all" ? "Simulating Attacks..." : "Run Full Red Team Suite (All 6)"}
        </button>
      </div>

      {ledgerValid !== null && (
        <div
          className="card"
          style={{
            marginBottom: "1.5rem",
            backgroundColor: ledgerValid ? "var(--accent-emerald-bg)" : "var(--accent-rose-bg)",
            borderColor: ledgerValid ? "var(--accent-emerald)" : "var(--accent-rose)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <span style={{ fontWeight: 700, color: ledgerValid ? "var(--accent-emerald)" : "var(--accent-rose)" }}>
                {ledgerValid ? "✓ ALL DEFENSIVE INVARIANTS HELD & LEDGER VALIDATED" : "✗ DEFENSE INTEGRITY COMPROMISED"}
              </span>
              <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginTop: "0.2rem" }}>
                Zero unauthorized captures. Zero money custodies. SHA-256 hash chains unbroken across all test runs.
              </p>
            </div>
            <div className="mono" style={{ fontSize: "0.8rem", color: "var(--text-primary)" }}>
              {results.filter((r) => r.passed).length} / {results.length} Defenses Held
            </div>
          </div>
        </div>
      )}

      {/* Scenario Grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 300px), 1fr))", gap: "1rem", marginBottom: "1.5rem" }}>
        {SCENARIOS.map((scen) => {
          const runRes = results.find((r) => r.scenario === scen.key);
          return (
            <div key={scen.key} className="card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.5rem" }}>
                <div>
                  <h3 style={{ fontSize: "1rem", fontWeight: 700 }}>{scen.title}</h3>
                  <div className="mono" style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                    {scen.key}
                  </div>
                </div>
                {runRes && (
                  <span
                    className="badge"
                    style={{
                      backgroundColor: runRes.passed ? "var(--accent-emerald-bg)" : "var(--accent-rose-bg)",
                      color: runRes.passed ? "var(--accent-emerald)" : "var(--accent-rose)",
                      border: `1px solid ${runRes.passed ? "var(--accent-emerald)" : "var(--accent-rose)"}`,
                    }}
                  >
                    {runRes.passed ? "DEFENSE HELD" : "FAILED"}
                  </span>
                )}
              </div>

              <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "0.75rem" }}>
                {scen.description}
              </p>

              <div style={{ fontSize: "0.775rem", color: "var(--text-muted)", display: "flex", flexDirection: "column", gap: "0.25rem", marginBottom: "1rem" }}>
                <div>Defensive Intercept: <strong style={{ color: "var(--accent-cyan)" }}>{scen.expected_layer}</strong></div>
                <div>Expected Outcome: <strong style={{ color: "var(--text-primary)" }}>{scen.expected_outcome}</strong></div>
                {runRes && <div>Actual Outcome: <strong style={{ color: runRes.passed ? "var(--accent-emerald)" : "var(--accent-rose)" }}>{runRes.status || runRes.actual_outcome}</strong> ({runRes.elapsed_ms}ms)</div>}
              </div>

              <button
                className="btn btn-secondary btn-sm"
                style={{ width: "100%" }}
                onClick={() => runSingleScenario(scen.key)}
                disabled={running}
              >
                {running && activeScenario === scen.key ? "Executing Attack..." : `Simulate ${scen.title}`}
              </button>
            </div>
          );
        })}
      </div>

      {/* Live Defense Logs */}
      <div className="card">
        <h3 style={{ fontSize: "0.95rem", fontWeight: 700, marginBottom: "0.5rem", color: "var(--text-secondary)" }}>
          DEFENSIVE AUDIT LOG STREAM
        </h3>
        <div className="arena-log">
          {logs.length === 0 ? (
            <div style={{ color: "var(--text-muted)" }}>Ready for simulation. Select a scenario above or run all.</div>
          ) : (
            logs.map((line, idx) => (
              <div key={idx} className="log-entry">
                <span className="log-ts">{line}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
