import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { LiquidGlassCursor } from "./LiquidGlassCursor";
import "./liquid-glass-cursor.css";
import "./styles.css";
import "./tailadmin-theme.css";
import "./motion.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><App /><LiquidGlassCursor /></React.StrictMode>
);
