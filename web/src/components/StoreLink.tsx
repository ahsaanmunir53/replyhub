// The website store (ReplyHub, Pro plan): the owner connects Shopify or WooCommerce with a
// read-only key, picks the hour of the daily WhatsApp report, and sees today's numbers.
// The key goes to the server once and is never shown again.
import { useEffect, useState } from "react";
import { api } from "../api";
import type { OwnerMe, Store, StoreIn } from "../api";
import type { Key } from "../i18n";
import { useLang } from "../lang";
import { formatMoney } from "../money";

type Saving = "idle" | "saving" | "saved" | "failed";
const HOURS = Array.from({ length: 24 }, (_, h) => h);

export function StorePanel({ me, token }: { me: OwnerMe; token: string }) {
  const { t, lang } = useLang();
  const [store, setStore] = useState<Store | null>(null);
  const [form, setForm] = useState<StoreIn>({
    platform: "shopify",
    store_url: "",
    key: "",
    secret: "",
    report_hour: 21,
  });
  const [state, setState] = useState<Saving>("idle");

  const show = (found: Store) => {
    setStore(found);
    setForm((now) => ({
      ...now,
      platform: found.platform ?? now.platform,
      store_url: found.store_url ?? now.store_url,
      report_hour: found.report_hour,
      key: "",
      secret: "",
    }));
  };

  useEffect(() => {
    api.store(token).then(show, () => {
      // The panel waits for the next visit; nothing else depends on it.
    });
  }, [token]);

  async function run(step: () => Promise<Store>) {
    setState("saving");
    try {
      show(await step());
      setState("saved");
    } catch {
      setState("failed");
    }
  }

  const set = (patch: Partial<StoreIn>) => {
    setForm((now) => ({ ...now, ...patch }));
    setState("idle");
  };
  const money = (minor: number) => formatMoney(minor, me.country, lang);
  const status: Partial<Record<Saving, Key>> = { saved: "console.saved", failed: "store.failed" };
  const today = store?.today;
  return (
    <section className="pay-panel store-panel" aria-labelledby="store-title" aria-busy={!store}>
      <h2 id="store-title" className="section-title">
        {t("store.title")}
      </h2>
      <p className="aside">{t("store.lede")}</p>
      {store?.connected && (
        <p className="aside" role="status">
          {store.synced_at
            ? t("store.synced", { when: new Date(store.synced_at).toLocaleString(lang) })
            : t("store.never")}
          {store.last_error && <span className="store-error"> {store.last_error}</span>}
        </p>
      )}
      {today && (
        <p className="store-today">
          {t("store.today_line", {
            orders: today.orders,
            sales: money(today.sales),
            cod: today.cod,
            pending: today.pending,
            unsent: today.unsent,
          })}
        </p>
      )}
      {store && (
        <div className="books-form">
          <label>
            {t("store.platform")}
            <select
              value={form.platform}
              onChange={(e) => set({ platform: e.target.value as StoreIn["platform"] })}
            >
              <option value="shopify">Shopify</option>
              <option value="woocommerce">WooCommerce</option>
            </select>
          </label>
          <label>
            {t("store.url")}
            <input
              value={form.store_url}
              maxLength={200}
              inputMode="url"
              placeholder={
                form.platform === "shopify" ? "mystore.myshopify.com" : "https://mystore.com"
              }
              onChange={(e) => set({ store_url: e.target.value })}
            />
          </label>
          <label>
            {t("store.key")}
            <input
              type="password"
              autoComplete="off"
              maxLength={200}
              value={form.key}
              placeholder={store.key_set ? t("store.key_set") : ""}
              onChange={(e) => set({ key: e.target.value })}
            />
          </label>
          {form.platform === "woocommerce" && (
            <label>
              {t("store.secret")}
              <input
                type="password"
                autoComplete="off"
                maxLength={200}
                value={form.secret}
                placeholder={store.key_set ? t("store.key_set") : ""}
                onChange={(e) => set({ secret: e.target.value })}
              />
            </label>
          )}
          <label>
            {t("store.hour")}
            <select
              value={form.report_hour}
              onChange={(e) => set({ report_hour: Number(e.target.value) })}
            >
              {HOURS.map((hour) => (
                <option key={hour} value={hour}>
                  {`${String(hour).padStart(2, "0")}:00`}
                </option>
              ))}
            </select>
          </label>
          <div className="import-actions">
            <button
              type="button"
              className="button button-ink button-small"
              disabled={state === "saving" || !form.store_url.trim()}
              onClick={() => void run(() => api.saveStore(token, form))}
            >
              {t("store.save")}
            </button>
            {store.connected && (
              <>
                <button
                  type="button"
                  className="action"
                  disabled={state === "saving"}
                  onClick={() => void run(() => api.syncStore(token))}
                >
                  {t("store.sync")}
                </button>
                <button
                  type="button"
                  className="action"
                  disabled={state === "saving"}
                  onClick={() => void run(() => api.removeStore(token))}
                >
                  {t("store.remove")}
                </button>
              </>
            )}
            {status[state] && (
              <span className="aside" role="status">
                {t(status[state] as Key)}
              </span>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
