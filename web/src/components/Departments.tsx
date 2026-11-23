// Departments (ReplyHub, Business plan): teams such as Sales, Delivery or Complaints. A chat
// whose first words match a department's keywords goes to it, and when it needs a person it
// goes to that department's member with the fewest open chats, like a ticket.
import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import type { Department } from "../api";
import { useLang } from "../lang";

type Member = { id: string; name: string; role: string; active: boolean };
const split = (text: string) =>
  text
    .split(/[,،\n]/)
    .map((w) => w.trim())
    .filter(Boolean);

export function DepartmentsPanel({ token }: { token: string }) {
  const { t } = useLang();
  const [list, setList] = useState<Department[] | null>(null);
  const [team, setTeam] = useState<Member[]>([]);
  const [name, setName] = useState("");
  const [words, setWords] = useState("");
  const [failed, setFailed] = useState(false);
  const load = useCallback(() => {
    api.departments(token).then(setList, () => setList([]));
    api.team(token).then(
      (found) => setTeam(found.filter((m) => m.active)),
      () => undefined,
    );
  }, [token]);
  useEffect(load, [load]);

  const run = (job: Promise<Department[]>) =>
    job.then(
      (found) => {
        setList(found);
        setFailed(false);
      },
      () => setFailed(true),
    );

  function add(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    void run(api.addDepartment(token, name, split(words))).then(() => {
      setName("");
      setWords("");
    });
  }

  const departmentOf = (staffId: string) =>
    list?.find((d) => d.members.includes(staffId))?.id ?? "";

  if (!list) return null;
  return (
    <section className="dept-panel" aria-labelledby="dept-title">
      <h2 id="dept-title" className="section-title">
        {t("dept.title")}
      </h2>
      <p className="aside">{t("dept.lede")}</p>
      <ol className="dept-how">
        <li>{t("dept.how1")}</li>
        <li>{t("dept.how2")}</li>
        <li>{t("dept.how3")}</li>
      </ol>
      {list.length > 0 && (
        <ul className="dept-list">
          {list.map((d) => (
            <li key={d.id} className="dept-card">
              <div className="dept-top">
                <strong>{d.name}</strong>
                <span className="pill">{t("dept.open", { count: d.open_chats })}</span>
              </div>
              <p className="dept-words">
                {d.keywords.length ? d.keywords.join(", ") : t("dept.no_words")}
              </p>
              <p className="aside">
                {d.members.length
                  ? team
                      .filter((m) => d.members.includes(m.id))
                      .map((m) => m.name)
                      .join(", ")
                  : t("dept.no_members")}
              </p>
              <button
                type="button"
                className="action"
                onClick={() => {
                  if (window.confirm(t("dept.remove_confirm")))
                    void run(api.removeDepartment(token, d.id));
                }}
              >
                {t("dept.remove")}
              </button>
            </li>
          ))}
        </ul>
      )}
      <form className="books-form dept-form" onSubmit={add}>
        <label>
          {t("dept.name")}
          <input
            required
            maxLength={60}
            dir="auto"
            placeholder={t("dept.name_example")}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label>
          {t("dept.words")}
          <input
            dir="auto"
            placeholder={t("dept.words_example")}
            value={words}
            onChange={(e) => setWords(e.target.value)}
          />
        </label>
        <button type="submit" className="button button-ink button-small">
          {t("dept.add")}
        </button>
      </form>
      {list.length > 0 && team.length > 0 && (
        <div className="dept-members">
          <h3>{t("dept.who")}</h3>
          <ul>
            {team.map((m) => (
              <li key={m.id}>
                <span dir="auto">{m.name}</span>
                <select
                  aria-label={t("dept.who_for", { name: m.name })}
                  value={departmentOf(m.id)}
                  onChange={(e) => void run(api.setDepartment(token, m.id, e.target.value || null))}
                >
                  <option value="">{t("dept.none")}</option>
                  {list.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
              </li>
            ))}
          </ul>
        </div>
      )}
      {failed && <p role="alert">{t("dept.failed")}</p>}
    </section>
  );
}
