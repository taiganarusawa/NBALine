// What every tab shares: the server's startup info (model, stats, payouts), the game date (one date for
// Best lines and Check lines), that day's players for the name suggestions, and short messages (toasts).
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, messageOf } from "../api";
import type { Meta, Player } from "../types";

interface AppState {
  meta: Meta;
  reloadMeta: () => Promise<void>;
  gameDate: string;
  setGameDate: (date: string) => void;
  players: Player[];
  gamesInfo: string;
  toast: (message: string) => void;
  /** Goes up by one whenever an update downloads new data, so tabs showing graded results reload. */
  dataVersion: number;
  newData: () => void;
}

const AppContext = createContext<AppState | null>(null);

export function useApp() {
  const app = useContext(AppContext);
  if (!app) throw new Error("useApp must be used inside <AppProvider>");
  return app;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [failed, setFailed] = useState("");
  const [gameDate, setGameDate] = useState("");
  const [players, setPlayers] = useState<Player[]>([]);
  const [gamesInfo, setGamesInfo] = useState("");
  const [dataVersion, setDataVersion] = useState(0);
  const [message, setMessage] = useState("");
  const toastTimer = useRef<number>(undefined);

  const reloadMeta = useCallback(async () => {
    try {
      const m = await api<Meta>("/api/meta");
      setMeta(m);
      setGameDate((date) => date || m.today);
    } catch (e) {
      setFailed(messageOf(e));
    }
  }, []);
  useEffect(() => { reloadMeta(); }, [reloadMeta]);

  // everyone playing on the chosen date, for the player-name suggestions
  useEffect(() => {
    if (!gameDate) return;
    let current = true;
    api<{ games: number; players: Player[] }>(`/api/players?date=${gameDate}`)
      .then((r) => {
        if (!current) return;
        setPlayers(r.players);
        setGamesInfo(r.games ? `${r.games} game(s) on ${gameDate}. Start typing a name to pick from that day's players.`
          : `No NBA games on ${gameDate}.`);
      })
      .catch((e) => current && setGamesInfo(messageOf(e)));
    return () => { current = false; };
  }, [gameDate]);

  const toast = useCallback((text: string) => {
    setMessage(text);
    clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setMessage(""), 2200);
  }, []);

  const newData = useCallback(() => setDataVersion((v) => v + 1), []);

  if (!meta) return <div className="top status">{failed || "Loading…"}</div>;
  return (
    <AppContext.Provider value={{ meta, reloadMeta, gameDate, setGameDate, players, gamesInfo, toast, dataVersion, newData }}>
      {children}
      <datalist id="playerList">
        {players.map((p) => (
          <option key={`${p.team}-${p.name}`} value={p.name}>{`${p.team} ${p.home ? "vs" : "@"} ${p.opp} · ${p.tip}`}</option>
        ))}
      </datalist>
      <div className={`toast${message ? "" : " hidden"}`} role="status">{message}</div>
    </AppContext.Provider>
  );
}
