// Signing back in to the console with the email and password set at sign-up. The token is
// kept in this browser (localStorage), so the console opens straight away next time.
import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import type { LoggedIn } from "../api";
import { Page, Problem } from "../components/Shell";
import { useLang } from "../lang";
import { readOwnerToken, saveOwnerToken } from "../owner";

export function LoginPage() {
  const { t } = useLang();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [shops, setShops] = useState<LoggedIn["shops"]>([]);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const signedIn = readOwnerToken() !== null;

  async function go(shop?: string) {
    setBusy(true);
    setFailed(false);
    try {
      const found = await api.login(email, password, shop);
      if (found.token) {
        saveOwnerToken(found.token);
        navigate("/owner", { replace: true });
        return;
      }
      setShops(found.shops);
    } catch {
      setFailed(true);
    }
    setBusy(false);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void go();
  }

  return (
    <Page>
      <section className="signup login" aria-labelledby="login-title">
        <h1 id="login-title" className="start-title">
          {t("login.title")}
        </h1>
        <p className="start-lede">{t("login.lede")}</p>
        {signedIn && (
          <p>
            <Link className="button button-ghost button-small" to="/owner">
              {t("login.open_console")}
            </Link>
          </p>
        )}
        {shops.length > 1 ? (
          <div className="login-pick">
            <p>{t("login.pick")}</p>
            <ul>
              {shops.map((shop) => (
                <li key={shop.slug}>
                  <button
                    type="button"
                    className="button button-ink"
                    disabled={busy}
                    onClick={() => void go(shop.slug)}
                  >
                    {shop.name}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <form className="books-form signup-form" onSubmit={submit}>
            <label>
              {t("signup.email")}
              <input
                required
                type="email"
                autoComplete="email"
                maxLength={160}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label>
              {t("login.password")}
              <input
                required
                type="password"
                autoComplete="current-password"
                maxLength={128}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {failed && <Problem message={t("login.failed")} />}
            <button type="submit" className="button button-ink" disabled={busy}>
              {busy ? t("login.busy") : t("login.submit")}
            </button>
          </form>
        )}
        <p className="aside">
          {t("login.no_account")} <Link to="/signup">{t("login.make_one")}</Link>
        </p>
        <p className="aside">{t("login.no_password")}</p>
      </section>
    </Page>
  );
}
