import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { DevilsAdvocates } from "@/routes/index";
import "@/styles.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Missing application root.");
}

createRoot(root).render(
  <StrictMode>
    <DevilsAdvocates />
  </StrictMode>,
);
