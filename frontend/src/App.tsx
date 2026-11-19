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
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

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
    setMobileMenuOpen(false);
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
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--accent-cyan)"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ display: "inline-block", verticalAlign: "middle" }}
          >
            <rect x="2" y="5" width="20" height="14" rx="2" />
            <line x1="2" y1="10" x2="22" y2="10" />
          </svg>
          <span style={{ fontWeight: 700, letterSpacing: "-0.02em" }}>PayLap</span>
          <span className="brand-badge">v0.3.0</span>
        </a>

        {/* Desktop nav links */}
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

        {/* Desktop meta + Mobile Hamburger button */}
        <div className="nav-meta">
          <span className="badge badge-simulated" style={{ display: "inline-flex" }}>
            <span className="badge-dot badge-dot-warning" />
            Simulated
          </span>

          {currentUser ? (
            <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
              <span className="mono" style={{ fontSize: "0.78rem", color: "var(--accent-cyan)", maxWidth: "150px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {currentUser.email}
              </span>
              <button className="btn btn-secondary btn-sm" onClick={handleLogout}>
                Sign Out
              </button>
            </div>
          ) : (
            <button className="btn btn-primary btn-sm" onClick={() => setShowAuthModal(true)}>
              Sign In
            </button>
          )}

          {/* Mobile hamburger menu toggle */}
          <button
            className="mobile-menu-btn"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle navigation menu"
          >
            {mobileMenuOpen ? "✕" : "☰"}
          </button>
        </div>
      </nav>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div className="mobile-nav-drawer">
          <button
            className={`nav-link ${currentPath === "/" || currentPath.startsWith("/contracts") ? "active" : ""}`}
            onClick={() => navigate("/")}
          >
            Contracts
          </button>
          <button
            className={`nav-link ${currentPath === "/playground" ? "active" : ""}`}
            onClick={() => navigate("/playground")}
          >
            Red Team Arena
          </button>
          <button
            className={`nav-link ${currentPath === "/settings" ? "active" : ""}`}
            onClick={() => navigate("/settings")}
          >
            Settings
          </button>
        </div>
      )}

      <main className="content-wrapper">{view}</main>

      <AuthModal
        isOpen={showAuthModal}
        onClose={() => setShowAuthModal(false)}
        onLoginSuccess={(user) => {
          setCurrentUser(user);
          navigate(currentPath);
        }}
      />
    </div>
  );
};
