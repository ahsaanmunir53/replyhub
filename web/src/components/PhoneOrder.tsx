// An order that came by phone call or in the shop: the owner types it in, and it joins the same
// order list as chat orders, with the price, stock and delivery charge worked out by code.
import { useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import type { OwnerProduct } from "../api";
import { useLang } from "../lang";
import { formatMoney } from "../money";

type Line = { variant: string; quantity: number };
const EMPTY = { name: "", phone: "", city: "", address: "", area: "" };

export function PhoneOrderPanel({
  token,
  country,
  products,
  onAdded,
}: {
  token: string;
  country: string;
  products: OwnerProduct[];
  onAdded: () => void;
}) {
  const { t, lang } = useLang();
  const choices = products
    .filter((p) => p.status === "active")
    .flatMap((p) =>
      p.variants.map((v) => ({
        id: v.id,
        label:
          [p.name, ...Object.values(v.options)].join(" · ") +
          ` (${formatMoney(v.price, country, lang)})`,
      })),
    );
  const [lines, setLines] = useState<Line[]>([{ variant: "", quantity: 1 }]);
  const [details, setDetails] = useState(EMPTY);
  const [done, setDone] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  function submit(event: FormEvent) {
    event.preventDefault();
    const chosen = lines.filter((l) => l.variant);
    if (!chosen.length) return;
    setBusy(true);
    setFailed(false);
    api
      .addPhoneOrder(
        token,
        chosen.map((l) => ({ variant_id: l.variant, quantity: l.quantity })),
        details,
      )
      .then(
        (placed) => {
          setDone(placed.code);
          setLines([{ variant: "", quantity: 1 }]);
          setDetails(EMPTY);
          onAdded();
        },
        () => setFailed(true),
      )
      .finally(() => setBusy(false));
  }

  return (
    <details className="pay-panel phone-order">
      <summary>
        <strong>{t("phone.title")}</strong>
        <span className="aside"> {t("phone.lede")}</span>
      </summary>
      {choices.length === 0 ? (
        <p className="aside">{t("phone.no_products")}</p>
      ) : (
        <form className="books-form" onSubmit={submit}>
          {lines.map((line, n) => (
            <div key={n} className="phone-line">
              <select
                required={n === 0}
                aria-label={t("phone.product")}
                value={line.variant}
                onChange={(e) =>
                  setLines(lines.map((l, i) => (i === n ? { ...l, variant: e.target.value } : l)))
                }
              >
                <option value="">{t("phone.product")}</option>
                {choices.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>
              <input
                type="number"
                min={1}
                max={99}
                aria-label={t("phone.quantity")}
                value={line.quantity}
                onChange={(e) =>
                  setLines(
                    lines.map((l, i) =>
                      i === n ? { ...l, quantity: Math.max(1, Number(e.target.value) || 1) } : l,
                    ),
                  )
                }
              />
            </div>
          ))}
          <button
            type="button"
            className="action"
            onClick={() => setLines([...lines, { variant: "", quantity: 1 }])}
          >
            {t("phone.another")}
          </button>
          {(["name", "phone", "city", "area", "address"] as const).map((field) => (
            <label key={field}>
              {t(`phone.${field}`)}
              <input
                required
                dir="auto"
                minLength={field === "phone" ? 7 : 2}
                value={details[field]}
                onChange={(e) => setDetails({ ...details, [field]: e.target.value })}
              />
            </label>
          ))}
          {failed && <p role="alert">{t("phone.failed")}</p>}
          {done && <p className="pw-box pw-done">{t("phone.added", { code: done })}</p>}
          <button type="submit" className="button button-ink button-small" disabled={busy}>
            {t("phone.submit")}
          </button>
        </form>
      )}
    </details>
  );
}
