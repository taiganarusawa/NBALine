import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import App from "./App";
import { AppProvider } from "./context/AppContext";
import { SlipProvider } from "./context/SlipContext";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AppProvider>
        <SlipProvider>
          <App />
        </SlipProvider>
      </AppProvider>
    </BrowserRouter>
  </StrictMode>,
);
