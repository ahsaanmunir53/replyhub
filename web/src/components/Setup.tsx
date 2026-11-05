// Getting started (ReplyHub): the few steps that make the assistant useful, each ticked
// once it is done. Shown at the top of the console until every step is done.
import { useEffect, useState } from "react";
import { api } from "../api";
import type { OwnerMe } from "../api";
import type { Key } from "../i18n";
import { useLang } from "../lang";

export function SetupPanel({ me, token }: { me: OwnerMe; token: string }) {
  const { t } = useLang();
  const [rules, setRules] = useState<boolean | null>(null);
  const [store, setStore] = useState<boolean | null>(null);
  const reports = me.features?.includes("reports") ?? false;

  useEffect(() => {
    api.rules(token).then(
      (found) => setRules(Boolean(found.hours || found.address || found.faqs.length)),
      () => setRules(false),
    );
    if (reports)
      api.store(token).then(
        (found) => setStore(found.connected),
        () => setStore(false),
      );
  }, [token, reports]);

  const steps: { key: Key; done: boolean; href: string; note?: Key }[] = [
    { key: "setup.rules", done: rules === true, href: "#sec-rules" },
    {
      key: "setup.whatsapp",
      done: me.whatsapp_connected === true,
      href: "#sec-settings",
      note: "setup.whatsapp_note",
    },
    ...(reports ? [{ key: "setup.store" as Key, done: store === true, href: "#sec-store" }] : []),
    { key: "setup.try", done: false, href: `s/${me.slug}/chat` },
  ];
  const needed = steps.filter((s) => s.key !== "setup.try");
  if (rules === null || needed.every((s) => s.done)) return null;
  return (
    <section className="pay-panel setup-panel" aria-labelledby="setup-title">
      <h2 id="setup-title" className="section-title">
        {t("setup.title")}
      </h2>
      <ol className="setup-steps">
        {steps.map((step) => (
          <li key={step.key} className={step.done ? "done" : undefined}>
            <a href={step.href}>{t(step.key)}</a>
            {step.done && <span className="aside"> {t("setup.done")}</span>}
            {!step.done && step.note && <p className="aside">{t(step.note)}</p>}
          </li>
        ))}
      </ol>
    </section>
  );
}
