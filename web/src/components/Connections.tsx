// Connections (ReplyHub): every place customers can reach the business, whether it is on, and
// what to do next. WhatsApp, Instagram and Messenger are connected by us on Meta; the website
// chat works at once; a Shopify or WooCommerce store is linked on the Website store page.
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { OwnerMe } from "../api";
import { copyText } from "../clipboard";
import type { Key } from "../i18n";
import { useLang } from "../lang";

type Card = {
  id: string;
  title: Key;
  body: Key;
  on: boolean;
  needs?: string; // the feature the plan must include
  action?: { label: Key; to: string };
};

export function ConnectionsPanel({
  me,
  token,
  canChange,
  onChanged,
}: {
  me: OwnerMe;
  token: string;
  canChange: boolean;
  onChanged: () => void;
}) {
  const { t } = useLang();
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const has = (feature: string) => (me.features ?? []).includes(feature);
  const chatUrl = `${window.location.origin}/s/${me.slug}/chat`;
  const button =
    `<a href="${chatUrl}" target="_blank" rel="noopener" ` +
    `style="position:fixed;bottom:20px;right:20px;padding:12px 18px;border-radius:24px;` +
    `background:#12a06b;color:#fff;font:600 15px sans-serif;text-decoration:none">` +
    `Chat with us</a>`;

  const cards: Card[] = [
    {
      id: "whatsapp",
      title: "conn.whatsapp",
      body: "conn.whatsapp_body",
      on: (me.channels ?? []).includes("whatsapp"),
    },
    {
      id: "web",
      title: "conn.web",
      body: "conn.web_body",
      on: true,
      action: { label: "conn.try_chat", to: `/s/${me.slug}/chat` },
    },
    {
      id: "store",
      title: "conn.store",
      body: "conn.store_body",
      on: false,
      needs: "reports",
      action: { label: "conn.open_store", to: "/owner/store" },
    },
    {
      id: "instagram",
      title: "conn.instagram",
      body: "conn.instagram_body",
      on: (me.channels ?? []).includes("instagram"),
      needs: "instagram",
    },
    {
      id: "messenger",
      title: "conn.messenger",
      body: "conn.messenger_body",
      on: (me.channels ?? []).includes("messenger"),
      needs: "messenger",
    },
  ];

  const toggleSelling = () => {
    setBusy(true);
    api.setSelling(token, !me.selling).then(
      () => {
        setBusy(false);
        onChanged();
      },
      () => setBusy(false),
    );
  };

  return (
    <div className="conn">
      <ul className="conn-grid">
        {cards.map((card) => {
          const locked = card.needs !== undefined && !has(card.needs);
          return (
            <li key={card.id} className={card.on ? "conn-card is-on" : "conn-card"}>
              <div className="conn-top">
                <h3>{t(card.title)}</h3>
                <span className={card.on ? "pill pill-on" : "pill"}>
                  {t(card.on ? "conn.on" : locked ? "conn.locked" : "conn.off")}
                </span>
              </div>
              <p>{t(card.body)}</p>
              {locked ? (
                <Link to="/owner/overview" className="button button-ghost button-small">
                  {t("conn.see_plans")}
                </Link>
              ) : (
                card.action && (
                  <Link to={card.action.to} className="button button-ghost button-small">
                    {t(card.action.label)}
                  </Link>
                )
              )}
            </li>
          );
        })}
      </ul>

      <div className="conn-block">
        <h3>{t("conn.button_title")}</h3>
        <p>{t("conn.button_body")}</p>
        <pre className="conn-code">{button}</pre>
        <button
          type="button"
          className="button button-ghost button-small"
          onClick={() => {
            void copyText(button).then(() => setCopied(true));
          }}
        >
          {t(copied ? "conn.copied" : "conn.copy")}
        </button>
      </div>

      {has("shop") && (
        <div className="conn-block">
          <h3>{t("conn.selling_title")}</h3>
          <p>{t("conn.selling_body")}</p>
          {canChange && (
            <button
              type="button"
              className={
                me.selling
                  ? "button button-ghost button-small"
                  : "button button-saffron button-small"
              }
              disabled={busy}
              onClick={toggleSelling}
            >
              {t(me.selling ? "conn.selling_off" : "conn.selling_on")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
