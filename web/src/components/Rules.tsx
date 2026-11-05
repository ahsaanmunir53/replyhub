// The assistant's rules (ReplyHub): what the business is, its timings and address, how
// customers buy, its policies, the owner's own questions and answers, the tone and what never
// to say. The assistant answers from these and the products; the rest comes to the owner.
import { useEffect, useState } from "react";
import { api } from "../api";
import type { Rules } from "../api";
import type { Key } from "../i18n";
import { useLang } from "../lang";

type Saving = "idle" | "saving" | "saved" | "failed";
type TextKey = Exclude<keyof Rules, "tone" | "faqs">;

const FIELDS: { key: TextKey; label: Key; max: number; rows: number }[] = [
  { key: "about", label: "rules.about", max: 500, rows: 2 },
  { key: "hours", label: "rules.hours", max: 300, rows: 1 },
  { key: "address", label: "rules.address", max: 300, rows: 1 },
  { key: "delivery", label: "rules.delivery", max: 500, rows: 2 },
  { key: "how_to_order", label: "rules.how_to_order", max: 500, rows: 2 },
  { key: "returns", label: "rules.returns", max: 500, rows: 2 },
  { key: "policies", label: "rules.policies", max: 1000, rows: 3 },
  { key: "avoid", label: "rules.avoid", max: 500, rows: 2 },
];
const TONES: { value: Rules["tone"]; label: Key }[] = [
  { value: "friendly", label: "rules.tone_friendly" },
  { value: "formal", label: "rules.tone_formal" },
  { value: "brief", label: "rules.tone_brief" },
];
const MAX_FAQS = 40;

export function RulesPanel({ token }: { token: string }) {
  const { t } = useLang();
  const [rules, setRules] = useState<Rules | null>(null);
  const [state, setState] = useState<Saving>("idle");

  useEffect(() => {
    api.rules(token).then(setRules, () => {
      // The panel waits for the next visit; nothing else depends on it.
    });
  }, [token]);

  const set = (patch: Partial<Rules>) => {
    setRules((now) => (now ? { ...now, ...patch } : now));
    setState("idle");
  };

  async function save() {
    if (!rules) return;
    const faqs = rules.faqs
      .map((f) => ({ question: f.question.trim(), answer: f.answer.trim() }))
      .filter((f) => f.question || f.answer);
    if (faqs.some((f) => !f.question || !f.answer)) {
      setState("failed");
      return;
    }
    setState("saving");
    try {
      setRules(await api.saveRules(token, { ...rules, faqs }));
      setState("saved");
    } catch {
      setState("failed");
    }
  }

  const status: Partial<Record<Saving, Key>> = { saved: "console.saved", failed: "rules.failed" };
  return (
    <section className="pay-panel rules-panel" aria-labelledby="rules-title" aria-busy={!rules}>
      <h2 id="rules-title" className="section-title">
        {t("rules.title")}
      </h2>
      <p className="aside">{t("rules.lede")}</p>
      {rules && (
        <div className="books-form">
          {FIELDS.map((field) => (
            <label key={field.key}>
              {t(field.label)}
              <textarea
                rows={field.rows}
                maxLength={field.max}
                dir="auto"
                value={rules[field.key]}
                onChange={(e) => set({ [field.key]: e.target.value })}
              />
            </label>
          ))}
          <label>
            {t("rules.tone")}
            <select
              value={rules.tone}
              onChange={(e) => set({ tone: e.target.value as Rules["tone"] })}
            >
              {TONES.map((tone) => (
                <option key={tone.value} value={tone.value}>
                  {t(tone.label)}
                </option>
              ))}
            </select>
          </label>
          <fieldset>
            <legend>{t("rules.faqs")}</legend>
            {rules.faqs.map((faq, index) => (
              <div key={index} className="rules-faq">
                <input
                  aria-label={t("rules.question")}
                  placeholder={t("rules.question")}
                  maxLength={200}
                  dir="auto"
                  value={faq.question}
                  onChange={(e) =>
                    set({
                      faqs: rules.faqs.map((f, i) =>
                        i === index ? { ...f, question: e.target.value } : f,
                      ),
                    })
                  }
                />
                <textarea
                  aria-label={t("rules.answer")}
                  placeholder={t("rules.answer")}
                  rows={2}
                  maxLength={600}
                  dir="auto"
                  value={faq.answer}
                  onChange={(e) =>
                    set({
                      faqs: rules.faqs.map((f, i) =>
                        i === index ? { ...f, answer: e.target.value } : f,
                      ),
                    })
                  }
                />
                <button
                  type="button"
                  className="action"
                  onClick={() => set({ faqs: rules.faqs.filter((_, i) => i !== index) })}
                >
                  {t("rules.remove")}
                </button>
              </div>
            ))}
            {rules.faqs.length < MAX_FAQS && (
              <button
                type="button"
                className="action"
                onClick={() => set({ faqs: [...rules.faqs, { question: "", answer: "" }] })}
              >
                {t("rules.add_faq")}
              </button>
            )}
          </fieldset>
          <div className="import-actions">
            <button
              type="button"
              className="button button-ink button-small"
              disabled={state === "saving"}
              onClick={() => void save()}
            >
              {t("rules.save")}
            </button>
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
