// How each plan works, on its own page so it can be shared with a new business owner.
import { Link } from "react-router-dom";
import { Page } from "../components/Shell";
import { PlanTour } from "../components/PlanTour";
import { DEMO_CHAT } from "../config";
import { useLang } from "../lang";

export function TourPage() {
  const { t } = useLang();
  return (
    <Page>
      <section className="signup">
        <PlanTour />
        <p className="signup-top">
          <Link className="button button-ink" to="/signup">
            {t("tour.start")}
          </Link>
          <Link className="button button-ghost" to={DEMO_CHAT}>
            {t("signup.try_demo")}
          </Link>
        </p>
      </section>
    </Page>
  );
}
