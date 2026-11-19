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
        return;
      }
    } catch {
      // Unauthenticated, try dev auto-login
    }

    // Auto-login seeded dev user if no session or key exists
    if (!storedUser && !storedKey) {
      try {
        const loginRes = await PayLapClient.post<any>("/v1/auth/login", {
          email: "dev@paylap.local",
          password: "Development1234!",
        });
        if (loginRes && loginRes.user) {
          setCurrentUser(loginRes.user);
          if (loginRes.csrf_token) {
            localStorage.setItem("paylap_csrf_token", loginRes.csrf_token);
          }
          localStorage.setItem("paylap_user", JSON.stringify(loginRes.user));
          window.dispatchEvent(new Event("paylap_auth_change"));
        }
      } catch {
        localStorage.setItem("paylap_api_key", "pl_test_devkey00000000_1234567890abcdef1234567890abcdef");
        setCurrentUser({ email: "dev@paylap.local", isApiKey: true });
        window.dispatchEvent(new Event("paylap_auth_change"));
      }
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

          <div className="desktop-only" style={{ alignItems: "center", gap: "0.6rem" }}>
            {currentUser ? (
              <>
                <span className="mono" style={{ fontSize: "0.78rem", color: "var(--accent-cyan)", maxWidth: "160px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {currentUser.email}
                </span>
                <button className="btn btn-secondary btn-sm" onClick={handleLogout}>
                  Sign Out
                </button>
              </>
            ) : (
              <button className="btn btn-primary btn-sm" onClick={() => setShowAuthModal(true)}>
                Sign In
              </button>
            )}
          </div>

          {/* Mobile hamburger menu toggle with clean SVG icon */}
          <button
            className="mobile-menu-btn"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle navigation menu"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              {mobileMenuOpen ? (
                <>
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </>
              ) : (
                <>
                  <line x1="3" y1="12" x2="21" y2="12" />
                  <line x1="3" y1="6" x2="21" y2="6" />
                  <line x1="3" y1="18" x2="21" y2="18" />
                </>
              )}
            </svg>
          </button>
        </div>
      </nav>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div className="mobile-nav-drawer">
          <div className="mobile-drawer-links">
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

          <div className="mobile-drawer-user">
            {currentUser ? (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <span className="badge-dot badge-dot-success" />
                  <span className="mono" style={{ fontSize: "0.8rem", color: "var(--accent-cyan)", maxWidth: "180px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {currentUser.email}
                  </span>
                </div>
                <button className="btn btn-secondary btn-sm" onClick={handleLogout}>
                  Sign Out
                </button>
              </div>
            ) : (
              <button
                className="btn btn-primary btn-sm"
                style={{ width: "100%", justifyContent: "center" }}
                onClick={() => {
                  setShowAuthModal(true);
                  setMobileMenuOpen(false);
                }}
              >
                Sign In
              </button>
            )}
          </div>
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
