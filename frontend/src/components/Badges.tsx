import React from "react";

export interface EnvironmentBadgeProps {
  environment: "simulated" | "sandbox" | "live" | string;
}

export const EnvironmentBadge: React.FC<EnvironmentBadgeProps> = ({ environment }) => {
  if (environment === "simulated") {
    return (
      <span className="badge badge-simulated" title="Simulated environment — dry run only">
        <span className="badge-dot badge-dot-warning" /> Simulated
      </span>
    );
  }
  if (environment === "sandbox") {
    return (
      <span className="badge badge-sandbox" title="PayPal Developer Sandbox">
        <span className="badge-dot badge-dot-info" /> Sandbox
      </span>
    );
  }
  if (environment === "live") {
    return (
      <span className="badge badge-live" title="Production PayPal with real money">
        <span className="badge-dot badge-dot-success" /> Live
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
  let dotCls = "badge-dot-default";

  if (norm === "FUNDED" || norm === "IN_PROGRESS" || norm === "VERIFYING") {
    cls = "badge-status-funded";
    dotCls = "badge-dot-info";
  } else if (norm === "COMPLETED" || norm === "PAID" || norm === "VERIFIED") {
    cls = "badge-status-completed";
    dotCls = "badge-dot-success";
  } else if (norm === "VOIDED" || norm === "REJECTED" || norm === "FAILED") {
    cls = "badge-status-voided";
    dotCls = "badge-dot-danger";
  } else if (norm === "BLOCKED") {
    cls = "badge-status-blocked";
    dotCls = "badge-dot-danger";
  }

  return (
    <span className={`badge ${cls}`}>
      <span className={`badge-dot ${dotCls}`} />
      {norm.replace(/_/g, " ")}
    </span>
  );
};
