// Why a business pays for ReplyHub: the problems owners who sell on WhatsApp, Instagram and
// Facebook meet every day, each shown as it goes today and as it goes with ReplyHub.
import { Link } from "react-router-dom";
import { DEMO_CHAT } from "../config";
import type { Key } from "../i18n";
import { useLang } from "../lang";

const PROBLEMS = [1, 2, 3, 4, 5, 6] as const;

export function WhyReplyHub() {
  const { t } = useLang();
  return (
    <section className="why" aria-labelledby="why-title">
      <h2 id="why-title" className="land-h2">
        {t("why.title")}
      </h2>
      <p className="aside">{t("why.lede")}</p>
      <ul className="why-grid">
        {PROBLEMS.map((n) => (
          <li key={n} className="why-card">
            <h3>{t(`why.p${n}_title` as Key)}</h3>
            <p className="why-before">
              <span>{t("why.before")}</span>
              {t(`why.p${n}_before` as Key)}
            </p>
            <p className="why-after">
              <span>{t("why.after")}</span>
              {t(`why.p${n}_after` as Key)}
            </p>
          </li>
        ))}
      </ul>
      <div className="why-gap">
        <h3>{t("why.gap_title")}</h3>
        <p>{t("why.gap_body")}</p>
        <Link className="button button-ink button-small" to={DEMO_CHAT}>
          {t("signup.try_demo")}
        </Link>
      </div>
    </section>
  );
}
