// Signing a business up for ReplyHub: one short form, then straight into the console on the
// Basic plan. The owner's WhatsApp number lets the assistant know the owner's own messages.
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import type { SignupIn, SignupOptions } from "../api";
import { Page, Problem } from "../components/Shell";
import { BASE_PATH } from "../config";
import { useLang } from "../lang";

const LANGS: { id: string; name: string }[] = [
  { id: "en", name: "English" },
  { id: "ar", name: "العربية" },
  { id: "ur-Latn", name: "Roman Urdu" },
  { id: "ur", name: "اردو" },
  { id: "hi", name: "हिन्दी" },
  { id: "bn", name: "বাংলা" },
  { id: "pa-Arab", name: "پنجابی" },
  { id: "sd", name: "سنڌي" },
  { id: "ps", name: "پښتو" },
];

export function SignupPage() {
  const { t } = useLang();
  const [options, setOptions] = useState<SignupOptions | null>(null);
  const [form, setForm] = useState<SignupIn>({
    business_name: "",
    business_type: "",
    country: "AE",
    city: "",
    owner_name: "",
    email: "",
    whatsapp: "",
    lang: "en",
  });
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api.signupOptions().then(
      (found) => {
        setOptions(found);
        setForm((now) => ({ ...now, business_type: found.business_types[0]?.id ?? "" }));
      },
      () => setFailed(true),
    );
  }, []);

  const set = (patch: Partial<SignupIn>) => setForm((now) => ({ ...now, ...patch }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailed(false);
    try {
      const made = await api.signup(form);
      window.location.assign(`${BASE_PATH}owner#t=${made.token}`);
    } catch {
      setFailed(true);
      setBusy(false);
    }
  }

  return (
    <Page>
      <section className="signup" aria-labelledby="signup-title">
        <h1 id="signup-title" className="start-title">
          {t("signup.title")}
        </h1>
        <p className="start-lede">{t("signup.lede")}</p>
        {options && !options.open && <Problem message={t("signup.closed")} />}
        {options?.open && (
          <form className="books-form signup-form" onSubmit={(e) => void submit(e)}>
            <label>
              {t("signup.business_name")}
              <input
                required
                minLength={2}
                maxLength={120}
                dir="auto"
                value={form.business_name}
                onChange={(e) => set({ business_name: e.target.value })}
              />
            </label>
            <label>
              {t("signup.business_type")}
              <select
                value={form.business_type}
                onChange={(e) => set({ business_type: e.target.value })}
              >
                {options.business_types.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("signup.country")}
              <select value={form.country} onChange={(e) => set({ country: e.target.value })}>
                {options.countries.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("signup.city")}
              <input
                required
                minLength={2}
                maxLength={80}
                dir="auto"
                value={form.city}
                onChange={(e) => set({ city: e.target.value })}
              />
            </label>
            <label>
              {t("signup.owner_name")}
              <input
                required
                minLength={2}
                maxLength={80}
                dir="auto"
                autoComplete="name"
                value={form.owner_name}
                onChange={(e) => set({ owner_name: e.target.value })}
              />
            </label>
            <label>
              {t("signup.email")}
              <input
                required
                type="email"
                maxLength={160}
                autoComplete="email"
                value={form.email}
                onChange={(e) => set({ email: e.target.value })}
              />
            </label>
            <label>
              {t("signup.whatsapp")}
              <input
                required
                type="tel"
                inputMode="tel"
                maxLength={24}
                autoComplete="tel"
                value={form.whatsapp}
                onChange={(e) => set({ whatsapp: e.target.value })}
              />
            </label>
            <label>
              {t("signup.lang")}
              <select value={form.lang} onChange={(e) => set({ lang: e.target.value })}>
                {LANGS.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </label>
            <p className="aside">{t("signup.plan_note")}</p>
            {failed && <Problem message={t("signup.failed")} />}
            <button type="submit" className="button button-ink" disabled={busy}>
              {t("signup.submit")}
            </button>
          </form>
        )}
      </section>
    </Page>
  );
}
