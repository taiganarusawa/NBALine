// The page: header, one tab per address (/bestlines, /check, /entries, /results, /longshots),
// and the hover box. Each tab is its own page component in pages/.
import { useEffect } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router";
import Header from "./components/Header";
import Tooltip from "./components/Tooltip";
import { useSlip } from "./context/SlipContext";
import BestLines from "./pages/BestLines";
import CheckLines from "./pages/CheckLines";
import LongShots from "./pages/LongShots";
import MyEntries from "./pages/MyEntries";
import Results from "./pages/Results";

const TABS = [
  { path: "/bestlines", name: "Best lines", page: <BestLines /> },
  { path: "/check", name: "Check lines", page: <CheckLines /> },
  { path: "/entries", name: "My entries", page: <MyEntries /> },
  { path: "/results", name: "Results", page: <Results /> },
  { path: "/longshots", name: "Long shots", page: <LongShots /> },
];

export default function App() {
  const { slip } = useSlip();
  const { pathname } = useLocation();
  useEffect(() => {
    const tab = TABS.find((t) => t.path === pathname);
    document.title = tab ? `${tab.name} · NBALine` : "NBALine";
  }, [pathname]);

  return (
    <>
      <Header />
      <nav className="tabs">
        {TABS.map((t, i) => (
          <NavLink key={t.path} to={t.path} className={({ isActive }) => `tab${isActive ? " active" : ""}`}>
            {i + 1} · {t.name}
            {t.path === "/entries" && slip.length > 0 && <span className="pill">{slip.length}</span>}
          </NavLink>
        ))}
      </nav>
      <main>
        <Routes>
          {TABS.map((t) => <Route key={t.path} path={t.path} element={t.page} />)}
          <Route path="*" element={<Navigate to="/bestlines" replace />} />
        </Routes>
      </main>
      <Tooltip />
    </>
  );
}
