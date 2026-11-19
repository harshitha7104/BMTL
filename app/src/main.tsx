import React, { useCallback, useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import App from "./App.tsx";
import LoginPage from "./components/LoginPage";
import { CurrentUser, SIGNED_OUT_EVENT, fetchCurrentUser, installSignedOutWatcher, signOut } from "./services/authService";

installSignedOutWatcher();

// Nothing behind the sign-in screen loads until the server confirms the session cookie.
function Root() {
  const [user, setUser] = useState<CurrentUser | null | undefined>(undefined);

  useEffect(() => {
    fetchCurrentUser().then(setUser).catch(() => setUser(null));
    const onSignedOut = () => setUser(null);
    window.addEventListener(SIGNED_OUT_EVENT, onSignedOut);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, onSignedOut);
  }, []);

  const handleSignOut = useCallback(async () => {
    await signOut().catch(() => undefined);
    setUser(null);
  }, []);

  if (user === undefined) return null;
  // Open testing (public_demo): visitors are guests; the owner signs in as admin at <link>#signin to see Records.
  if (user === null || (window.location.hash === "#signin" && user.role !== "admin" && user.auth_mode === "public_demo"))
    return <LoginPage onSignedIn={u => { if (window.location.hash === "#signin") history.replaceState(null, "", "/"); setUser(u); }} />;
  const local = user.auth_mode === "disabled_local_dev" || (user.auth_mode === "public_demo" && user.role !== "admin");
  return <App key={user.username} username={user.username} role={user.role} recordsVisible={!!user.records_visible} onSignOut={local ? undefined : handleSignOut} />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(<Root />);
