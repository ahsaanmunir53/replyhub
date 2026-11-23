// The plan panel (ReplyHub): the trial or the plan, how much of it is used, and the three plans
// with a button to ask for one. Paying happens with us, outside the app; the plan turns on
// once we have the money.
import { useEffect, useState } from "react";
import { api } from "../api";
import type { PaidPlan, PlanView } from "../api";
import { languageOf, localeOf } from "../i18n";
import type { Key } from "../i18n";
import { useLang } from "../lang";

function day(iso: string, lang: string) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString(localeOf(languageOf(lang)), {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function PlanPanel({ token, canAsk }: { token: string; canAsk: boolean }) {
  const { t, lang } = useLang();
  const [view, setView] = useState<PlanView | null>(null);
  const [busy, setBusy] = useState<PaidPlan | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    api.plan(token).then(
      (found) => live && setView(found),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, [token]);

  if (failed) return null;
  if (!view) return null;

  const ask = (plan: PaidPlan) => {
    setBusy(plan);
    api.askForPlan(token, plan).then(
      (found) => {
        setView(found);
        setBusy(null);
      },
      () => setBusy(null),
    );
  };
  const trial = view.plan === "trial";
  const share = view.limit > 0 ? Math.min(view.used / view.limit, 1) : 0;
  const planName = (id: string) => t(`plan.${id}` as Key);

  return (
    <section className="pay-panel plan-panel" aria-labelledby="plan-title">
      <h2 id="plan-title" className="section-title">
        {t("plan.title")}: {planName(view.plan)}
      </h2>
      {view.stopped && (
        <p className="plan-stopped" role="status">
          {t(`plan.stopped_${view.stopped}` as Key)}
        </p>
      )}
      <div className="plan-meter">
        <p>
          {t(trial ? "plan.trial_usage" : "plan.month_usage", {
            used: view.used,
            limit: view.limit,
          })}
        </p>
        <div
          className="plan-bar"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={view.limit}
          aria-valuenow={view.used}
          aria-label={t(trial ? "plan.trial_usage" : "plan.month_usage", {
            used: view.used,
            limit: view.limit,
          })}
        >
          <span style={{ width: `${Math.round(share * 100)}%` }} />
        </div>
        {trial && view.trial_ends && (
          <p className="aside">
            {t("plan.trial_ends", { date: day(view.trial_ends, lang) })}
          </p>
        )}
        {!trial && view.paid_until && (
          <p className="aside">{t("plan.paid_until", { date: day(view.paid_until, lang) })}</p>
        )}
      </div>

      {view.requested && (
        <p className="plan-requested" role="status">
          {t("plan.requested", { plan: planName(view.requested) })}{" "}
          {view.contact && (
            <a href={view.contact} target="_blank" rel="noreferrer">
              {t("plan.message_us")}
            </a>
          )}
        </p>
      )}

      <ul className="plan-options">
        {view.options.map((option) => {
          const current = option.id === view.plan;
          return (
            <li key={option.id} className={current ? "current" : undefined}>
              <h3>{planName(option.id)}</h3>
              <p className="plan-price">{option.price ?? t("plan.price_ask")}</p>
              <p className="aside">{t("plan.replies_month", { count: option.replies })}</p>
              <ul className="plan-features">
                {option.features.map((feature) => (
                  <li key={feature}>{t(`plan.f_${feature}` as Key)}</li>
                ))}
              </ul>
              {current ? (
                <p className="aside">{t("plan.current_badge")}</p>
              ) : (
                canAsk && (
                  <button
                    type="button"
                    className={option.id === "pro" ? "button button-saffron button-small" : "button button-ghost button-small"}
                    disabled={busy !== null || view.requested === option.id}
                    onClick={() => ask(option.id)}
                  >
                    {t("plan.choose", { plan: planName(option.id) })}
                  </button>
                )
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
