import React, { useEffect, useState } from "react";
import { ContractsList } from "./views/ContractsList";
import { ContractDetail } from "./views/ContractDetail";
import { NewContractBuilder } from "./views/NewContractBuilder";
import { Playground } from "./views/Playground";
import { Settings } from "./views/Settings";
import { PublicReceiptView } from "./views/PublicReceiptView";

export const App: React.FC = () => {
  const [currentPath, setCurrentPath] = useState<string>(window.location.pathname);

  useEffect(() => {
    const handlePopState = () => {
      setCurrentPath(window.location.pathname);
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigate = (path: string) => {
    window.history.pushState({}, "", path);
    setCurrentPath(path);
  };

  // Route parsing
  let view = <ContractsList onSelectContract={(id) => navigate(`/contracts/${id}`)} onNavigateNew={() => navigate("/contracts/new")} />;

  if (currentPath === "/contracts/new") {
    view = (
      <NewContractBuilder
        onContractCreated={(id) => navigate(`/contracts/${id}`)}
        onCancel={() => navigate("/")}
      />
    );
  } else if (currentPath.startsWith("/contracts/")) {
    const contractId = currentPath.replace("/contracts/", "");
    view = <ContractDetail contractId={contractId} onBack={() => navigate("/")} />;
  } else if (currentPath === "/playground") {
    view = <Playground />;
  } else if (currentPath === "/settings") {
    view = <Settings />;
  } else if (currentPath.startsWith("/receipts/")) {
    const shareToken = currentPath.replace("/receipts/", "");
    return (
      <div className="app-container">
        <div className="content-wrapper">
          <PublicReceiptView shareToken={shareToken} />
        </div>
      </div>
    );
  }

  return (
    <div className="app-container">
      <nav className="navbar">
        <a
          href="/"
          className="nav-brand"
          onClick={(e) => {
            e.preventDefault();
            navigate("/");
          }}
        >
          <span style={{ color: "var(--accent-cyan)", fontSize: "1.3rem" }}>⚡</span> PayLap
          <span className="brand-badge">v0.3.0</span>
        </a>

        <ul className="nav-links">
          <li>
            <button
              className={`nav-link ${currentPath === "/" || currentPath.startsWith("/contracts") ? "active" : ""}`}
              onClick={() => navigate("/")}
            >
              Contracts
            </button>
          </li>
          <li>
            <button
              className={`nav-link ${currentPath === "/playground" ? "active" : ""}`}
              onClick={() => navigate("/playground")}
            >
              Red Team Arena
            </button>
          </li>
          <li>
            <button
              className={`nav-link ${currentPath === "/settings" ? "active" : ""}`}
              onClick={() => navigate("/settings")}
            >
              Settings
            </button>
          </li>
        </ul>

        <div className="nav-meta">
          <span className="badge badge-simulated">Simulated Mode Active</span>
        </div>
      </nav>

      <main className="content-wrapper">{view}</main>
    </div>
  );
};
