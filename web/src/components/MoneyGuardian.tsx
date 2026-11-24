// Money Guardian (ReplyHub): what couriers owe and what the bank proves, each order's real
// profit, disputes with couriers, courier scorecards and customers to check. Every figure
// comes from the API, counted by code; nothing here is estimated.
import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import type { Guardian, GuardianCase, OwnerMe } from "../api";
import type { Key } from "../i18n";
import { useLang } from "../lang";
import { formatMoney } from "../money";

type Tab = "overview" | "cod" | "profit" | "cases" | "couriers" | "watch";
const TABS: Tab[] = ["overview", "cod", "profit", "cases", "couriers", "watch"];
const CASE_KINDS = [
  "false_attempt",
  "unjustified_rto",
  "cod_missing",
  "wrong_deduction",
  "lost",
  "damaged",
] as const;
const CASE_STATUSES = ["open", "sent", "acknowledged", "resolved", "rejected"] as const;

export function MoneyGuardianPanel({ me, token }: { me: OwnerMe; token: string }) {
  const { t, lang } = useLang();
  const [tab, setTab] = useState<Tab>("overview");
  const [days, setDays] = useState(30);
  const [city, setCity] = useState("");
  const [data, setData] = useState<Guardian | null>(null);
  const [failed, setFailed] = useState(false);
  const [note, setNote] = useState("");
  const money = (minor: number | null | undefined) =>
    minor === null || minor === undefined ? "—" : formatMoney(minor, me.country, lang);
  const load = useCallback(() => {
    api.guardian(token, days, city).then(
      (found) => {
        setData(found);
        setFailed(false);
      },
      () => setFailed(true),
    );
  }, [token, days, city]);
  useEffect(load, [load]);

  async function upload(kind: "courier" | "bank", file: File, courier = "") {
    try {
      if (kind === "bank") {
        const report = await api.guardianBank(token, file);
        setNote(t("mg.bank_done", { credits: report.credits, proved: report.proved.length }));
      } else {
        const report = await api.uploadSettlement(token, file, courier);
        setNote(t("mg.sheet_done", { matched: report.matched, rows: report.rows }));
      }
      load();
    } catch {
      setNote(t("mg.upload_failed"));
    }
  }

  if (failed) return <p role="alert">{t("mg.failed")}</p>;
  if (!data) return <p className="aside">{t("mg.loading")}</p>;
  const s = data.summary;
  const tiles: [Key, string, string][] = [
    ["mg.t_unpaid", money(s.unpaid), "mg.h_unpaid"],
    ["mg.t_unproven", money(s.unproven), "mg.h_unproven"],
    ["mg.t_at_risk", money(s.at_risk), "mg.h_at_risk"],
    ["mg.t_unreconciled", String(s.unreconciled), "mg.h_unreconciled"],
    ["mg.t_profit", money(s.net_profit), "mg.h_profit"],
    ["mg.t_recovered", money(s.recovered), "mg.h_recovered"],
  ];

  return (
    <section className="mg" aria-labelledby="mg-title">
      <h2 id="mg-title" className="section-title">
        {t("mg.title")}
      </h2>
      <p className="aside">{t("mg.lede")}</p>
      <div className="mg-bar">
        <div className="khata-kinds" role="tablist" aria-label={t("mg.title")}>
          {TABS.map((id) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              onClick={() => setTab(id)}
            >
              {t(`mg.tab_${id}` as Key)}
            </button>
          ))}
        </div>
        <label className="mg-days">
          <span className="sr-only">{t("mg.period")}</span>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 30, 90].map((d) => (
              <option key={d} value={d}>
                {t("mg.days", { days: d })}
              </option>
            ))}
          </select>
        </label>
      </div>
      {note && <p className="pw-box pw-done">{note}</p>}

      {tab === "overview" && (
        <>
          <ul className="cb-tiles mg-tiles">
            {tiles.map(([label, value, help]) => (
              <li key={label} title={t(help as Key)}>
                <strong>{value}</strong>
                <span>{t(label)}</span>
                <small>{t(help as Key)}</small>
              </li>
            ))}
          </ul>
          <h3>{t("mg.alerts")}</h3>
          {data.alerts.length === 0 ? (
            <p className="aside">{t("mg.no_alerts")}</p>
          ) : (
            <ul className="mg-alerts">
              {data.alerts.map((alert, n) => (
                <li key={n} className={`mg-alert is-${alert.level}`}>
                  {t(`mg.a_${alert.key}` as Key, {
                    ...alert,
                    amount: money(alert.amount as number | undefined),
                  })}
                </li>
              ))}
            </ul>
          )}
          <Settings token={token} data={data} money={money} onSaved={load} />
          <Attempt
            token={token}
            onDone={(asked) => setNote(t(asked ? "mg.asked" : "mg.not_asked"))}
          />
        </>
      )}

      {tab === "cod" && (
        <>
          <p className="aside">{t("mg.cod_lede")}</p>
          <div className="mg-uploads">
            <CourierUpload onFile={(file, courier) => void upload("courier", file, courier)} />
            <label className="button button-ghost button-small mg-file">
              {t("mg.upload_bank")}
              <input
                type="file"
                accept=".csv,.xlsx,.xls"
                hidden
                onChange={(e) => e.target.files?.[0] && void upload("bank", e.target.files[0])}
              />
            </label>
          </div>
          <Table
            empty={t("mg.no_cod")}
            head={[
              "mg.c_order",
              "mg.c_courier",
              "mg.c_expected",
              "mg.c_reported",
              "mg.c_banked",
              "mg.c_state",
            ]}
            rows={data.cod.map((c) => [
              c.code,
              c.courier || "—",
              money(c.expected),
              money(c.reported),
              money(c.banked),
              `${t(`mg.s_${c.state}` as Key)}${c.overdue ? ` · ${t("mg.overdue", { days: c.days })}` : ""}`,
            ])}
          />
          {data.payouts.length > 0 && (
            <>
              <h3>{t("mg.payouts")}</h3>
              <Table
                empty=""
                head={["mg.c_sheet", "mg.c_courier", "mg.c_paid_out", "mg.c_bank"]}
                rows={data.payouts.map((p) => [
                  p.name,
                  p.courier || "—",
                  money(p.paid_out),
                  t(p.banked ? "mg.bank_yes" : "mg.bank_no"),
                ])}
              />
            </>
          )}
        </>
      )}

      {tab === "profit" && (
        <>
          <p className="aside">{t("mg.profit_lede")}</p>
          <Table
            empty={t("mg.no_profit")}
            head={[
              "mg.c_order",
              "mg.c_revenue",
              "mg.c_goods",
              "mg.c_courier_cost",
              "mg.c_other",
              "mg.c_net",
            ]}
            rows={data.profits.map((p) => [
              p.status === "returned" ? `${p.code} (${t("mg.returned")})` : p.code,
              money(p.revenue),
              money(p.goods),
              p.courier === null ? "—" : money(p.courier + p.returned),
              money(p.packaging + p.ads + p.payment),
              p.unknown.length
                ? `${money(p.net)} · ${t("mg.missing", { what: p.unknown.map((u) => t(`mg.u_${u}` as Key)).join(", ") })}`
                : money(p.net),
            ])}
          />
        </>
      )}

      {tab === "cases" && <Cases token={token} cases={data.cases} money={money} onChange={load} />}

      {tab === "couriers" && (
        <>
          <p className="aside">{t("mg.couriers_lede")}</p>
          <label className="mg-city">
            {t("mg.city")}
            <input value={city} dir="auto" onChange={(e) => setCity(e.target.value)} />
          </label>
          <Table
            empty={t("mg.no_couriers")}
            head={[
              "mg.c_courier",
              "mg.c_sent",
              "mg.c_delivered",
              "mg.c_returned",
              "mg.c_first",
              "mg.c_denied",
              "mg.c_days",
              "mg.c_pay_days",
              "mg.c_unpaid",
            ]}
            rows={data.couriers.map((c) => [
              c.courier,
              String(c.sent),
              pct(c.delivered_pct),
              pct(c.returned_pct),
              pct(c.first_try_pct),
              String(c.denied),
              c.days_to_deliver === null ? "—" : String(c.days_to_deliver),
              c.days_to_pay === null ? "—" : String(c.days_to_pay),
              money(c.unpaid),
            ])}
          />
        </>
      )}

      {tab === "watch" && (
        <>
          <p className="aside">{t("mg.watch_lede")}</p>
          <Table
            empty={t("mg.no_watch")}
            head={["mg.c_customer", "mg.c_delivered", "mg.c_returned", "mg.c_cancelled"]}
            rows={data.watch.map((w) => [
              w.name || t("mg.no_name"),
              String(w.delivered),
              String(w.returned),
              String(w.cancelled),
            ])}
          />
        </>
      )}
    </section>
  );
}

function pct(value: number | null) {
  return value === null ? "—" : `${value}%`;
}

function Table({ head, rows, empty }: { head: string[]; rows: string[][]; empty: string }) {
  const { t } = useLang();
  if (rows.length === 0) return empty ? <p className="aside">{empty}</p> : null;
  return (
    <div className="cb-table-wrap">
      <table className="cb-table">
        <thead>
          <tr>
            {head.map((h) => (
              <th key={h} scope="col">
                {t(h as Key)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, n) => (
            <tr key={n}>
              {row.map((cell, i) =>
                i === 0 ? (
                  <th key={i} scope="row">
                    {cell}
                  </th>
                ) : (
                  <td key={i}>{cell}</td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CourierUpload({ onFile }: { onFile: (file: File, courier: string) => void }) {
  const { t } = useLang();
  const [courier, setCourier] = useState("");
  return (
    <div className="mg-courier-upload">
      <input
        placeholder={t("mg.courier_name")}
        aria-label={t("mg.courier_name")}
        value={courier}
        onChange={(e) => setCourier(e.target.value)}
      />
      <label className="button button-ink button-small mg-file">
        {t("mg.upload_courier")}
        <input
          type="file"
          accept=".csv,.xlsx,.xls"
          hidden
          onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0], courier)}
        />
      </label>
    </div>
  );
}

function Settings({
  token,
  data,
  money,
  onSaved,
}: {
  token: string;
  data: Guardian;
  money: (minor: number | null | undefined) => string;
  onSaved: () => void;
}) {
  const { t } = useLang();
  const [form, setForm] = useState({
    packaging: "",
    ads: "",
    payment_percent: "",
    overdue_days: "",
  });
  const now = data.settings;
  function save(event: FormEvent) {
    event.preventDefault();
    const body: Record<string, string | number> = {};
    if (form.packaging) body.packaging = form.packaging;
    if (form.ads) body.ads = form.ads;
    if (form.payment_percent) body.payment_percent = Number(form.payment_percent);
    if (form.overdue_days) body.overdue_days = Number(form.overdue_days);
    void api.guardianSettings(token, body).then(onSaved, () => undefined);
  }
  return (
    <details className="pay-panel mg-settings">
      <summary>
        <strong>{t("mg.settings")}</strong>{" "}
        <span className="aside">
          {t("mg.settings_now", {
            packaging: money((now.packaging as number) ?? 0),
            ads: money((now.ads as number) ?? 0),
            days: (now.overdue_days as number) ?? 10,
          })}
        </span>
      </summary>
      <form className="books-form" onSubmit={save}>
        {(["packaging", "ads", "payment_percent", "overdue_days"] as const).map((key) => (
          <label key={key}>
            {t(`mg.set_${key}` as Key)}
            <input
              inputMode="decimal"
              value={form[key]}
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
            />
          </label>
        ))}
        <button type="submit" className="button button-ink button-small">
          {t("mg.save")}
        </button>
      </form>
    </details>
  );
}

function Attempt({ token, onDone }: { token: string; onDone: (asked: boolean) => void }) {
  const { t } = useLang();
  const [code, setCode] = useState("");
  const [note, setNote] = useState("");
  return (
    <details className="pay-panel mg-settings">
      <summary>
        <strong>{t("mg.attempt_title")}</strong>{" "}
        <span className="aside">{t("mg.attempt_lede")}</span>
      </summary>
      <form
        className="books-form"
        onSubmit={(event) => {
          event.preventDefault();
          void api.guardianAttempt(token, code.trim(), note).then(
            (r) => onDone(r.asked),
            () => onDone(false),
          );
        }}
      >
        <label>
          {t("mg.c_order")}
          <input required value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} />
        </label>
        <label>
          {t("mg.attempt_note")}
          <input value={note} dir="auto" onChange={(e) => setNote(e.target.value)} />
        </label>
        <button type="submit" className="button button-ink button-small">
          {t("mg.attempt_send")}
        </button>
      </form>
    </details>
  );
}

function Cases({
  token,
  cases,
  money,
  onChange,
}: {
  token: string;
  cases: GuardianCase[];
  money: (minor: number | null | undefined) => string;
  onChange: () => void;
}) {
  const { t } = useLang();
  const [text, setText] = useState<Record<string, string>>({});
  const [recover, setRecover] = useState<Record<string, string>>({});
  const [form, setForm] = useState({ order: "", kind: "damaged", at_stake: "", note: "" });
  return (
    <>
      <p className="aside">{t("mg.cases_lede")}</p>
      {cases.length === 0 && <p className="aside">{t("mg.no_cases")}</p>}
      <ul className="dept-list mg-cases">
        {cases.map((c) => (
          <li key={c.id} className="dept-card">
            <div className="dept-top">
              <strong>
                {c.order} · {t(`mg.k_${c.kind}` as Key)}
              </strong>
              <span className={c.status === "resolved" ? "pill pill-on" : "pill"}>
                {t(`mg.st_${c.status}` as Key)}
              </span>
            </div>
            <p className="aside">
              {c.courier || "—"} · {t("mg.at_stake")}: {money(c.at_stake)}
              {c.recovered ? ` · ${t("mg.recovered")}: ${money(c.recovered)}` : ""}
              {c.opened_by === "code" ? ` · ${t("mg.by_code")}` : ""}
            </p>
            <ol className="mg-timeline">
              {c.timeline.map((step, n) => (
                <li key={n}>
                  <small>{step.at.replace("T", " ")}</small> {step.text}
                </li>
              ))}
            </ol>
            <div className="mg-case-actions">
              <select
                aria-label={t("mg.status")}
                value={c.status}
                onChange={(e) =>
                  void api.guardianCase(token, c.id, { status: e.target.value }).then(onChange)
                }
              >
                {CASE_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {t(`mg.st_${s}` as Key)}
                  </option>
                ))}
              </select>
              <input
                className="mg-recover"
                inputMode="decimal"
                placeholder={t("mg.recovered_ask")}
                aria-label={t("mg.recovered_ask")}
                value={recover[c.id] ?? ""}
                onChange={(e) => setRecover({ ...recover, [c.id]: e.target.value })}
              />
              <button
                type="button"
                className="action"
                disabled={!recover[c.id]}
                onClick={() =>
                  void api
                    .guardianCase(token, c.id, { recovered: recover[c.id] ?? "0" })
                    .then(onChange)
                }
              >
                {t("mg.recovered")}
              </button>
              <button
                type="button"
                className="action"
                onClick={() =>
                  void api
                    .guardianComplaint(token, c.id)
                    .then((r) => setText({ ...text, [c.id]: r.text }))
                }
              >
                {t("mg.complaint")}
              </button>
            </div>
            {text[c.id] && (
              <>
                <pre className="conn-code mg-complaint">{text[c.id]}</pre>
                <button
                  type="button"
                  className="action"
                  onClick={() => void navigator.clipboard?.writeText(text[c.id] ?? "")}
                >
                  {t("conn.copy")}
                </button>
              </>
            )}
          </li>
        ))}
      </ul>
      <details className="pay-panel mg-settings">
        <summary>
          <strong>{t("mg.new_case")}</strong>
        </summary>
        <form
          className="books-form"
          onSubmit={(event) => {
            event.preventDefault();
            void api
              .guardianNewCase(token, {
                order: form.order.trim(),
                kind: form.kind,
                at_stake: form.at_stake || "0",
                note: form.note,
              })
              .then(onChange, () => undefined);
          }}
        >
          <label>
            {t("mg.c_order")}
            <input
              required
              value={form.order}
              onChange={(e) => setForm({ ...form, order: e.target.value.toUpperCase() })}
            />
          </label>
          <label>
            {t("mg.kind")}
            <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              {CASE_KINDS.map((k) => (
                <option key={k} value={k}>
                  {t(`mg.k_${k}` as Key)}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("mg.at_stake")}
            <input
              inputMode="decimal"
              value={form.at_stake}
              onChange={(e) => setForm({ ...form, at_stake: e.target.value })}
            />
          </label>
          <label>
            {t("mg.note")}
            <input
              dir="auto"
              value={form.note}
              onChange={(e) => setForm({ ...form, note: e.target.value })}
            />
          </label>
          <button type="submit" className="button button-ink button-small">
            {t("mg.open_case")}
          </button>
        </form>
      </details>
    </>
  );
}
