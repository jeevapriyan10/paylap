import React, { useEffect, useState } from "react";
import { PayLapClient } from "./api/client";
import { AuthModal } from "./components/AuthModal";
import { ContractsList } from "./views/ContractsList";
import { ContractDetail } from "./views/ContractDetail";
import { NewContractBuilder } from "./views/NewContractBuilder";
import { Playground } from "./views/Playground";
import { Settings } from "./views/Settings";
import { PublicReceiptView } from "./views/PublicReceiptView";

export const App: React.FC = () => {
  const [currentPath, setCurrentPath] = useState<string>(window.location.pathname);
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [currentUser, setCurrentUser] = useState<any>(null);

  useEffect(() => {
    const handlePopState = () => {
      setCurrentPath(window.location.pathname);
    };
    window.addEventListener("popstate", handlePopState);

    // Initial session/key check
    checkAuthStatus();

    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const checkAuthStatus = async () => {
    const storedKey = localStorage.getItem("paylap_api_key");
    const storedUser = localStorage.getItem("paylap_user");
    if (storedUser) {
      try {
        setCurrentUser(JSON.parse(storedUser));
      } catch {
        // fallback
      }
    } else if (storedKey) {
      setCurrentUser({ email: "API Key Active", isApiKey: true });
    }

    try {
      const res = await PayLapClient.get<any>("/v1/auth/me");
      if (res && res.user) {
        setCurrentUser(res.user);
        localStorage.setItem("paylap_user", JSON.stringify(res.user));
      }
    } catch {
      // Unauthenticated, leave null
    }
  };

  const handleLogout = async () => {
    try {
      await PayLapClient.post("/v1/auth/logout");
    } catch {
      // ignore
    }
    localStorage.removeItem("paylap_api_key");
    localStorage.removeItem("paylap_user");
    localStorage.removeItem("paylap_csrf_token");
    setCurrentUser(null);
    window.location.reload();
  };

  const navigate = (path: string) => {
    window.history.pushState({}, "", path);
    setCurrentPath(path);
  };

  // Route parsing
  let view = (
    <ContractsList
      onSelectContract={(id) => navigate(`/contracts/${id}`)}
      onNavigateNew={() => navigate("/contracts/new")}
      onOpenAuth={() => setShowAuthModal(true)}
    />
  );

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

          {currentUser ? (
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <span className="mono" style={{ fontSize: "0.8rem", color: "var(--accent-cyan)" }}>
                {currentUser.email}
              </span>
              <button className="btn btn-secondary btn-sm" onClick={handleLogout}>
                Sign Out
              </button>
            </div>
          ) : (
            <button className="btn btn-primary btn-sm" onClick={() => setShowAuthModal(true)}>
              ⚡ Sign In
            </button>
          )}
        </div>
      </nav>

      <main className="content-wrapper">{view}</main>

      <AuthModal
        isOpen={showAuthModal}
        onClose={() => setShowAuthModal(false)}
        onLoginSuccess={(user) => {
          setCurrentUser(user);
          // Reload view
          navigate(currentPath);
        }}
      />
    </div>
  );
};

