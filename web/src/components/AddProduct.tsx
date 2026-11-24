// Adding a product from plain boxes: name, price, stock and one option such as colour or size.
// The same product can also be added by telling the assistant, or from a sheet.
import { useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import { useLang } from "../lang";

const EMPTY = { name: "", price: "", cost: "", stock: "", option: "", values: "" };

export function AddProductPanel({ token, onAdded }: { token: string; onAdded: () => void }) {
  const { t } = useLang();
  const [form, setForm] = useState(EMPTY);
  const [done, setDone] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<typeof EMPTY>) => setForm((now) => ({ ...now, ...patch }));

  function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailed(false);
    api
      .addProduct(token, {
        name: form.name,
        price: form.price,
        unit_cost: form.cost === "" ? null : form.cost,
        stock: form.stock === "" ? null : Number(form.stock),
        option: form.option,
        values: form.values
          .split(/[,،]/)
          .map((v) => v.trim())
          .filter(Boolean),
      })
      .then(
        (added) => {
          setDone(added.name);
          setForm(EMPTY);
          onAdded();
        },
        () => setFailed(true),
      )
      .finally(() => setBusy(false));
  }

  return (
    <details className="pay-panel phone-order" open>
      <summary>
        <strong>{t("addp.title")}</strong>
        <span className="aside"> {t("addp.lede")}</span>
      </summary>
      <form className="books-form" onSubmit={submit}>
        <label>
          {t("addp.name")}
          <input
            required
            minLength={2}
            maxLength={160}
            dir="auto"
            value={form.name}
            onChange={(e) => set({ name: e.target.value })}
          />
        </label>
        <label>
          {t("addp.price")}
          <input
            required
            inputMode="decimal"
            pattern="[0-9]+([.][0-9]{1,2})?"
            value={form.price}
            onChange={(e) => set({ price: e.target.value })}
          />
        </label>
        <label>
          {t("addp.cost")}
          <input
            inputMode="decimal"
            pattern="[0-9]+([.][0-9]{1,2})?"
            value={form.cost}
            onChange={(e) => set({ cost: e.target.value })}
          />
        </label>
        <label>
          {t("addp.stock")}
          <input
            type="number"
            min={0}
            value={form.stock}
            onChange={(e) => set({ stock: e.target.value })}
          />
        </label>
        <label>
          {t("addp.option")}
          <input
            maxLength={30}
            dir="auto"
            placeholder={t("addp.option_example")}
            value={form.option}
            onChange={(e) => set({ option: e.target.value })}
          />
        </label>
        <label>
          {t("addp.values")}
          <input
            dir="auto"
            placeholder={t("addp.values_example")}
            value={form.values}
            onChange={(e) => set({ values: e.target.value })}
          />
        </label>
        {failed && <p role="alert">{t("addp.failed")}</p>}
        {done && <p className="pw-box pw-done">{t("addp.added", { name: done })}</p>}
        <button type="submit" className="button button-ink button-small" disabled={busy}>
          {t("addp.submit")}
        </button>
      </form>
    </details>
  );
}
