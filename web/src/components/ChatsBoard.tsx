// The chats overview (ReplyHub): how much customers wrote, how much the assistant and the team
// answered, and where the chats came from. The owner picks how to see it: charts, number
// cards or a table; the choice is remembered in this browser.
import { useState } from "react";
import type { Dashboard } from "../api";
import type { Key } from "../i18n";
import { useLang } from "../lang";

type Chats = NonNullable<Dashboard["chats"]>;
type View = "charts" | "cards" | "table";
const VIEW_KEY = "replyhub.dash.view";
const SERIES = [
  { id: "incoming", label: "dash.s_incoming", color: "var(--c1)" },
  { id: "assistant", label: "dash.s_assistant", color: "var(--c2)" },
  { id: "staff", label: "dash.s_staff", color: "var(--c3)" },
] as const;
const CHANNEL_KEY: Record<string, Key> = {
  whatsapp: "conn.whatsapp",
  web: "conn.web",
  webchat: "conn.web",
  instagram: "conn.instagram",
  messenger: "conn.messenger",
};

function savedView(): View {
  try {
    const found = localStorage.getItem(VIEW_KEY);
    return found === "cards" || found === "table" ? found : "charts";
  } catch {
    return "charts";
  }
}

export function ChatsBoard({ chats }: { chats: Chats }) {
  const { t, lang } = useLang();
  const [view, setView] = useState<View>(savedView);
  const pick = (next: View) => {
    setView(next);
    try {
      localStorage.setItem(VIEW_KEY, next);
    } catch {
      // The choice then lasts for this page only.
    }
  };
  const day = (iso: string) =>
    new Date(`${iso}T12:00:00`).toLocaleDateString(lang, { day: "numeric", month: "short" });
  const tiles: [Key, number][] = [
    ["dash.t_chats", chats.chats],
    ["dash.s_incoming", chats.incoming],
    ["dash.s_assistant", chats.assistant],
    ["dash.s_staff", chats.staff],
    ["dash.t_handed", chats.handed_over],
    ["dash.t_waiting", chats.waiting],
  ];
  const answered = chats.incoming ? Math.round((chats.assistant / chats.incoming) * 100) : 0;

  return (
    <section className="chats-board" aria-labelledby="chats-board-title">
      <div className="cb-head">
        <div>
          <h3 id="chats-board-title">{t("dash.chats_title")}</h3>
          <p className="aside">{t("dash.chats_lede", { share: answered })}</p>
        </div>
        <div className="khata-kinds cb-views" role="radiogroup" aria-label={t("dash.view")}>
          {(["charts", "cards", "table"] as const).map((id) => (
            <button
              key={id}
              type="button"
              role="radio"
              aria-checked={view === id}
              onClick={() => pick(id)}
            >
              {t(`dash.v_${id}` as Key)}
            </button>
          ))}
        </div>
      </div>

      {view !== "table" && (
        <ul className="cb-tiles">
          {tiles.map(([label, value]) => (
            <li key={label}>
              <strong>{value.toLocaleString(lang)}</strong>
              <span>{t(label)}</span>
            </li>
          ))}
        </ul>
      )}

      {view === "charts" && (
        <div className="cb-charts">
          <DailyLines chats={chats} day={day} />
          <Bars
            title={t("dash.by_channel")}
            rows={Object.entries(chats.channels).map(([id, n]) => [
              CHANNEL_KEY[id] ? t(CHANNEL_KEY[id]) : id,
              n,
            ])}
            empty={t("dash.none_yet")}
          />
          <Bars
            title={t("dash.by_department")}
            rows={Object.entries(chats.departments)}
            empty={t("dash.no_departments")}
          />
        </div>
      )}

      {view === "table" && (
        <div className="cb-table-wrap">
          <table className="cb-table">
            <thead>
              <tr>
                <th scope="col">{t("dash.day")}</th>
                <th scope="col">{t("dash.t_chats")}</th>
                {SERIES.map((s) => (
                  <th key={s.id} scope="col">
                    {t(s.label)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...chats.daily].reverse().map((row) => (
                <tr key={row.day}>
                  <th scope="row">{day(row.day)}</th>
                  <td>{row.chats}</td>
                  <td>{row.incoming}</td>
                  <td>{row.assistant}</td>
                  <td>{row.staff}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function DailyLines({ chats, day }: { chats: Chats; day: (iso: string) => string }) {
  const { t } = useLang();
  const [focus, setFocus] = useState<number | null>(null);
  const data = chats.daily;
  const width = 640;
  const height = 200;
  const left = 30;
  const right = 12;
  const top = 12;
  const bottom = 26;
  const most = Math.max(4, ...data.flatMap((d) => [d.incoming, d.assistant, d.staff]));
  const ceil = Math.ceil(most / 4) * 4;
  const x = (i: number) => left + ((i + 0.5) * (width - left - right)) / data.length;
  const y = (v: number) => top + (1 - v / ceil) * (height - top - bottom);
  const every = Math.ceil(data.length / 7);
  const shown = focus === null ? null : data[focus];

  return (
    <figure className="cb-chart cb-wide">
      <figcaption>{t("dash.per_day")}</figcaption>
      <ul className="cb-legend">
        {SERIES.map((s) => (
          <li key={s.id}>
            <i style={{ background: s.color }} />
            {t(s.label)}
          </li>
        ))}
      </ul>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={t("dash.per_day")}
        onMouseLeave={() => setFocus(null)}
      >
        {[0, ceil / 2, ceil].map((v) => (
          <g key={v}>
            <line x1={left} x2={width - right} y1={y(v)} y2={y(v)} className="cb-grid" />
            <text x={left - 6} y={y(v) + 4} textAnchor="end" className="cb-axis">
              {v}
            </text>
          </g>
        ))}
        {data.map((d, i) =>
          i % every === 0 || i === data.length - 1 ? (
            <text key={d.day} x={x(i)} y={height - 6} textAnchor="middle" className="cb-axis">
              {day(d.day)}
            </text>
          ) : null,
        )}
        {focus !== null && (
          <line x1={x(focus)} x2={x(focus)} y1={top} y2={height - bottom} className="cb-cross" />
        )}
        {data.map((d, i) =>
          SERIES.map((s, k) => {
            const slot = (width - left - right) / data.length;
            const bar = Math.max(2, Math.min(14, (slot - 6) / 3));
            const bx = x(i) - (bar * 3 + 4) / 2 + k * (bar + 2);
            return (
              <rect
                key={`${s.id}${d.day}`}
                x={bx}
                y={y(d[s.id])}
                width={bar}
                height={Math.max(0, y(0) - y(d[s.id]))}
                rx={2}
                fill={s.color}
              />
            );
          }),
        )}
        {data.map((d, i) => (
          <rect
            key={`hit${d.day}`}
            x={x(i) - (width - left) / data.length / 2}
            y={0}
            width={(width - left) / data.length}
            height={height}
            fill="transparent"
            onMouseEnter={() => setFocus(i)}
            onClick={() => setFocus(i)}
          />
        ))}
      </svg>
      <p className="cb-tip" aria-live="polite">
        {shown
          ? `${day(shown.day)}: ${t("dash.tip", {
              incoming: shown.incoming,
              assistant: shown.assistant,
              staff: shown.staff,
            })}`
          : t("dash.tip_hint")}
      </p>
    </figure>
  );
}

function Bars({ title, rows, empty }: { title: string; rows: [string, number][]; empty: string }) {
  const most = Math.max(1, ...rows.map(([, n]) => n));
  const sorted = [...rows].sort((a, b) => b[1] - a[1]);
  return (
    <figure className="cb-chart">
      <figcaption>{title}</figcaption>
      {sorted.length === 0 ? (
        <p className="aside">{empty}</p>
      ) : (
        <ul className="cb-bars">
          {sorted.map(([name, n]) => (
            <li key={name}>
              <span className="cb-bar-name">{name}</span>
              <span className="cb-bar-track">
                <span className="cb-bar" style={{ width: `${(n / most) * 100}%` }} />
              </span>
              <span className="cb-bar-n">{n}</span>
            </li>
          ))}
        </ul>
      )}
    </figure>
  );
}
