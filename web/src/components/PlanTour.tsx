// How each plan works, shown rather than told: pick Basic, Pro or Business and a short chat
// plays out on a phone, the way a customer and the assistant would really talk on that plan.
// Beside it: what the plan gives, what stays locked (and which plan opens it), how each
// channel is connected, and where replies go. Motion stops for people who ask for less.
import { useEffect, useState } from "react";
import type { Key } from "../i18n";
import { useLang } from "../lang";

type PlanId = "basic" | "pro" | "business";
type Who = "customer" | "assistant" | "staff" | "event";
type Line = { who: Who; text: Key };

const FEATURES: { key: Key; from: PlanId }[] = [
  { key: "plan.f_assistant", from: "basic" },
  { key: "plan.f_rules", from: "basic" },
  { key: "tour.f_webchat", from: "basic" },
  { key: "plan.f_inbox", from: "pro" },
  { key: "plan.f_shop", from: "pro" },
  { key: "plan.f_owner_whatsapp", from: "pro" },
  { key: "plan.f_reports", from: "pro" },
  { key: "plan.f_team", from: "business" },
  { key: "tour.f_departments", from: "business" },
  { key: "plan.f_broadcasts", from: "business" },
  { key: "plan.f_instagram", from: "business" },
  { key: "plan.f_messenger", from: "business" },
];
const ORDER: PlanId[] = ["basic", "pro", "business"];

const PLANS: Record<PlanId, { for: Key; channel: Key; script: Line[]; connect: Key[] }> = {
  basic: {
    for: "tour.basic_for",
    channel: "conn.whatsapp",
    script: [
      { who: "customer", text: "tour.b1" },
      { who: "assistant", text: "tour.b2" },
      { who: "customer", text: "tour.b3" },
      { who: "assistant", text: "tour.b4" },
      { who: "event", text: "tour.b5" },
    ],
    connect: ["tour.c_wa", "tour.c_web", "tour.c_rules"],
  },
  pro: {
    for: "tour.pro_for",
    channel: "conn.web",
    script: [
      { who: "customer", text: "tour.p1" },
      { who: "assistant", text: "tour.p2" },
      { who: "customer", text: "tour.p3" },
      { who: "assistant", text: "tour.p4" },
      { who: "event", text: "tour.p5" },
      { who: "staff", text: "tour.p6" },
    ],
    connect: ["tour.c_wa", "tour.c_web", "tour.c_products", "tour.c_store"],
  },
  business: {
    for: "tour.business_for",
    channel: "conn.instagram",
    script: [
      { who: "customer", text: "tour.x1" },
      { who: "event", text: "tour.x2" },
      { who: "assistant", text: "tour.x3" },
      { who: "event", text: "tour.x4" },
      { who: "staff", text: "tour.x5" },
    ],
    connect: ["tour.c_wa", "tour.c_ig", "tour.c_staff", "tour.c_dept"],
  },
};

function quiet(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  );
}

function Phone({ plan, run }: { plan: PlanId; run: number }) {
  const { t } = useLang();
  const script = PLANS[plan].script;
  const [shown, setShown] = useState(quiet() ? script.length : 1);
  useEffect(() => {
    if (quiet()) {
      setShown(script.length);
      return undefined;
    }
    setShown(1);
    let n = 1;
    const timer = window.setInterval(() => {
      n += 1;
      setShown(n);
      if (n >= script.length) window.clearInterval(timer);
    }, 1400);
    return () => window.clearInterval(timer);
  }, [plan, run, script.length]);
  return (
    <div className="tour-phone" aria-live="polite">
      <div className="tour-phone-bar">
        <span>{t(PLANS[plan].channel)}</span>
      </div>
      <ol className="tour-lines">
        {script.slice(0, shown).map((line, n) => (
          <li key={`${plan}${run}${n}`} className={`tour-line is-${line.who}`}>
            {line.who !== "customer" && line.who !== "event" && (
              <span className="tour-who">
                {t(line.who === "assistant" ? "tour.who_assistant" : "tour.who_staff")}
              </span>
            )}
            {t(line.text)}
          </li>
        ))}
      </ol>
    </div>
  );
}

export function PlanTour({ start = "pro" }: { start?: PlanId }) {
  const { t } = useLang();
  const [plan, setPlan] = useState<PlanId>(start);
  const [run, setRun] = useState(0);
  const rank = ORDER.indexOf(plan);

  return (
    <section className="tour" aria-labelledby="tour-title">
      <h2 id="tour-title" className="land-h2">
        {t("tour.title")}
      </h2>
      <p className="aside">{t("tour.lede")}</p>
      <div className="khata-kinds tour-tabs" role="tablist" aria-label={t("tour.title")}>
        {ORDER.map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={plan === id}
            onClick={() => {
              setPlan(id);
              setRun((n) => n + 1);
            }}
          >
            {t(`plan.${id}` as Key)}
          </button>
        ))}
      </div>
      <p className="tour-for">{t(PLANS[plan].for)}</p>
      <div className="tour-grid">
        <div className="tour-demo">
          <h3>{t("tour.watch")}</h3>
          <Phone plan={plan} run={run} />
          <button type="button" className="action" onClick={() => setRun((n) => n + 1)}>
            {t("tour.replay")}
          </button>
        </div>
        <div className="tour-info">
          <h3>{t("tour.get")}</h3>
          <ul className="tour-features">
            {FEATURES.map((f) => {
              const open = ORDER.indexOf(f.from) <= rank;
              return (
                <li key={f.key} className={open ? "is-on" : "is-locked"}>
                  <span aria-hidden="true" className="tour-mark">
                    {open ? "✓" : "—"}
                  </span>
                  <span>
                    {t(f.key)}
                    {!open && (
                      <small> {t("tour.unlock_on", { plan: t(`plan.${f.from}` as Key) })}</small>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
          <h3>{t("tour.connect")}</h3>
          <ol className="tour-steps">
            {PLANS[plan].connect.map((key) => (
              <li key={key}>{t(key)}</li>
            ))}
          </ol>
        </div>
      </div>
      <h3 className="tour-flow-title">{t("tour.flow")}</h3>
      <ol className="tour-flow">
        <li>{t("tour.flow1")}</li>
        <li>{t("tour.flow2")}</li>
        <li>{t("tour.flow3")}</li>
        <li>{t("tour.flow4")}</li>
      </ol>
    </section>
  );
}
