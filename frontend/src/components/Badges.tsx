import React from "react";

export interface EnvironmentBadgeProps {
  environment: "simulated" | "sandbox" | "live" | string;
}

export const EnvironmentBadge: React.FC<EnvironmentBadgeProps> = ({ environment }) => {
  if (environment === "simulated") {
    return (
      <span className="badge badge-simulated" title="Simulated environment — dry run only">
        <span style={{ fontSize: "1.1em" }}>⚠</span> Simulated (Dry Run)
      </span>
    );
  }
  if (environment === "sandbox") {
    return (
      <span className="badge badge-sandbox" title="PayPal Developer Sandbox">
        <span style={{ fontSize: "1.1em" }}>⚡</span> Sandbox
      </span>
    );
  }
  if (environment === "live") {
    return (
      <span className="badge badge-live" title="Production PayPal with real money">
        <span style={{ fontSize: "1.1em" }}>●</span> Live
      </span>
    );
  }
  return <span className="badge">{environment}</span>;
};

export interface StatusBadgeProps {
  status: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status }) => {
  const norm = (status || "").toUpperCase();
  let cls = "badge-status-awaiting";

  if (norm === "FUNDED" || norm === "IN_PROGRESS" || norm === "VERIFYING") {
    cls = "badge-status-funded";
  } else if (norm === "COMPLETED" || norm === "PAID" || norm === "VERIFIED") {
    cls = "badge-status-completed";
  } else if (norm === "VOIDED" || norm === "REJECTED" || norm === "FAILED") {
    cls = "badge-status-voided";
  } else if (norm === "BLOCKED") {
    cls = "badge-status-blocked";
  }

  return <span className={`badge ${cls}`}>{norm.replace(/_/g, " ")}</span>;
};
