import { useEffect, useState } from "react";
import { api } from "./api";
import LeadQueue from "./views/LeadQueue";
import LeadDetail from "./views/LeadDetail";
import PasteInbound from "./views/PasteInbound";
import KpiView from "./views/KpiView";
import VisibilityView from "./views/VisibilityView";

// Hash routes: #/leads, #/leads/<id>, #/paste, #/kpi, #/visibility
function useHashRoute(): string[] {
  const read = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => setRoute(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

const NAV = [
  { href: "#/leads", label: "Leads", match: "leads" },
  { href: "#/paste", label: "Paste message", match: "paste" },
  { href: "#/kpi", label: "KPI pack", match: "kpi" },
  { href: "#/visibility", label: "AI visibility", match: "visibility" },
];

export default function App() {
  const route = useHashRoute();
  const [mode, setMode] = useState<string | null>(null);
  useEffect(() => {
    api.health().then((h) => setMode(h.mode)).catch(() => setMode("API unreachable"));
  }, []);

  const section = route[0] ?? "leads";
  let view;
  if (section === "leads" && route[1]) view = <LeadDetail personId={decodeURIComponent(route[1])} />;
  else if (section === "paste") view = <PasteInbound />;
  else if (section === "kpi") view = <KpiView />;
  else if (section === "visibility") view = <VisibilityView />;
  else view = <LeadQueue />;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">Stargo <span>GTM pipeline</span></div>
        <nav>
          {NAV.map((item) => (
            <a key={item.href} href={item.href}
               className={section === item.match ? "active" : undefined}>{item.label}</a>
          ))}
        </nav>
        {mode && <div className={`mode ${mode.startsWith("rules") ? "fallback" : ""}`}>{mode}</div>}
      </header>
      <main>{view}</main>
      <footer>Nothing is sent from this app. Drafts need human approval and are sent by hand.</footer>
    </div>
  );
}
